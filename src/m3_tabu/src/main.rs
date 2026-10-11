// Méthode 3 : recherche tabou sur l'affectation des datasets aux créneaux, rôles fixés.
// Objectif f = consommation pondérée (pts, prix duaux LP) - lambda * sum_s e_s^2 (concentration de l'excès e_s = sum - lb),
// record = consommation pondérée minimale. Mouvements : retrait vers P, déplacement, insertion depuis P, échange.
// Usage : m3_tabu <in> <out> [seed] [time_s] [tenure] [lambda] [ncand] [stagn] [pert]
use std::env;
use std::fs;
use std::io::Write;
use std::time::Instant;

struct Rng(u64);
impl Rng {
    fn next(&mut self) -> u64 {
        let mut x = self.0;
        x ^= x << 13;
        x ^= x >> 7;
        x ^= x << 17;
        self.0 = x;
        x.wrapping_mul(0x2545F4914F6CDD1D)
    }
    fn below(&mut self, n: usize) -> usize {
        (self.next() % (n as u64)) as usize
    }
}

#[derive(Clone, Copy, Debug)]
enum Mv {
    Remove(u32),
    Move(u32, u32),
    Insert(u32, u32),
    Swap(u32, u32),
    SwapRemove(u32, u32, u32),
    Cycle3Remove(u32, u32, u32, u32), // d1: A->B, d2: B->C, d2p: C->A, puis retrait de d3 (A)
}

struct Sys {
    nd: usize,
    ns: usize, // indice ns = pool P des datasets libres
    dt: Vec<u8>,
    dsz: Vec<i64>,
    dfree: Vec<bool>,
    dw: Vec<i64>,
    slb: Vec<i64>,
    sub: Vec<i64>,
    sfo: Vec<bool>,
    ssum: Vec<i64>,
    members: Vec<Vec<u32>>,
    pos: Vec<u32>,
    assign: Vec<u32>,
    by_type: [Vec<u32>; 4],
    sizes: [Vec<i64>; 4],
    slots_by_type: [Vec<u32>; 4],
    cons_w: i64,
    cons_raw: i64,
    sum_e2: i64,
    lam: f64,
    mu: f64,
}

impl Sys {
    /// distance du créneau a à son prochain retrait possible (membre de taille <= largeur de fenêtre), avec e donné,
    /// en ignorant skip1/skip2 et en ajoutant un dataset de taille add (si >= 0)
    fn need(&self, a: usize, e: i64, skip1: u32, skip2: u32, add: i64) -> i64 {
        let w = self.sub[a] - self.slb[a];
        let mut best = i64::MAX;
        for &d in &self.members[a] {
            if d == skip1 || d == skip2 { continue; }
            let sz = self.dsz[d as usize];
            if sz <= w { let v = (sz - e).max(0); if v < best { best = v; } }
        }
        if add >= 0 && add <= w { let v = (add - e).max(0); if v < best { best = v; } }
        if best == i64::MAX { 0 } else { best }
    }
    fn pot(&self, a: usize, e: i64, skip1: u32, skip2: u32, add: i64) -> f64 {
        if self.mu == 0.0 { return 0.0; }
        self.mu * (self.need(a, e, skip1, skip2, add) as f64).sqrt()
    }
    fn e(&self, a: usize) -> i64 {
        self.ssum[a] - self.slb[a]
    }
    fn room(&self, a: usize) -> i64 {
        self.sub[a] - self.ssum[a]
    }
    fn f(&self) -> f64 {
        self.cons_w as f64 / 1e6 - self.lam * self.sum_e2 as f64
    }
    fn detach(&mut self, d: usize) {
        let a = self.assign[d] as usize;
        let p = self.pos[d] as usize;
        let last = *self.members[a].last().unwrap();
        self.members[a].swap_remove(p);
        if (last as usize) != d {
            self.pos[last as usize] = p as u32;
        }
        if a < self.ns {
            let e0 = self.e(a);
            self.ssum[a] -= self.dsz[d];
            let e1 = self.e(a);
            self.sum_e2 += e1 * e1 - e0 * e0;
            self.cons_w -= self.dw[d] * self.dsz[d];
            self.cons_raw -= self.dsz[d];
        }
    }
    fn attach(&mut self, d: usize, b: usize) {
        self.assign[d] = b as u32;
        self.pos[d] = self.members[b].len() as u32;
        self.members[b].push(d as u32);
        if b < self.ns {
            let e0 = self.e(b);
            self.ssum[b] += self.dsz[d];
            let e1 = self.e(b);
            self.sum_e2 += e1 * e1 - e0 * e0;
            self.cons_w += self.dw[d] * self.dsz[d];
            self.cons_raw += self.dsz[d];
        }
    }
    fn apply(&mut self, mv: Mv) {
        match mv {
            Mv::Remove(d) => {
                self.detach(d as usize);
                let ns = self.ns;
                self.attach(d as usize, ns);
            }
            Mv::Move(d, b) | Mv::Insert(d, b) => {
                self.detach(d as usize);
                self.attach(d as usize, b as usize);
            }
            Mv::Swap(d1, d2) => {
                let a = self.assign[d1 as usize] as usize;
                let b = self.assign[d2 as usize] as usize;
                self.detach(d1 as usize);
                self.detach(d2 as usize);
                self.attach(d1 as usize, b);
                self.attach(d2 as usize, a);
            }
            Mv::SwapRemove(d1, d2, d3) => {
                self.apply(Mv::Swap(d1, d2));
                self.apply(Mv::Remove(d3));
            }
            Mv::Cycle3Remove(d1, d2, d2p, d3) => {
                let a = self.assign[d1 as usize] as usize;
                let b = self.assign[d2 as usize] as usize;
                let c = self.assign[d2p as usize] as usize;
                self.detach(d1 as usize);
                self.detach(d2 as usize);
                self.detach(d2p as usize);
                self.attach(d1 as usize, b);
                self.attach(d2 as usize, c);
                self.attach(d2p as usize, a);
                self.apply(Mv::Remove(d3));
            }
        }
    }
    fn undo_cycle(&mut self, d1: u32, d2: u32, d2p: u32, d3: u32, a: usize, b: usize, c: usize) {
        self.detach(d3 as usize);
        self.attach(d3 as usize, a);
        self.detach(d1 as usize);
        self.detach(d2 as usize);
        self.detach(d2p as usize);
        self.attach(d1 as usize, a);
        self.attach(d2 as usize, b);
        self.attach(d2p as usize, c);
    }
    /// delta par application/annulation + test des fenêtres des créneaux touchés (None si infaisable)
    fn delta_cycle(&mut self, d1: u32, d2: u32, d2p: u32, d3: u32) -> Option<f64> {
        let a = self.assign[d1 as usize] as usize;
        let b = self.assign[d2 as usize] as usize;
        let c = self.assign[d2p as usize] as usize;
        let f0 = self.f();
        self.apply(Mv::Cycle3Remove(d1, d2, d2p, d3));
        let mut ok = true;
        for &x in &[a, b, c] {
            if x < self.ns && (self.ssum[x] < self.slb[x] || self.ssum[x] > self.sub[x]) { ok = false; }
        }
        let f1 = self.f();
        self.undo_cycle(d1, d2, d2p, d3, a, b, c);
        if ok { Some(f1 - f0) } else { None }
    }
    // delta de f (sans appliquer)
    fn delta(&self, mv: Mv) -> f64 {
        let lam = self.lam;
        match mv {
            Mv::Remove(d) => {
                let d = d as usize;
                let a = self.assign[d] as usize;
                let s = self.dsz[d];
                let ea = self.e(a);
                -(self.dw[d] * s) as f64 / 1e6 - lam * ((s * s - 2 * ea * s) as f64)
                    + self.pot(a, ea - s, d as u32, u32::MAX, -1) - self.pot(a, ea, u32::MAX, u32::MAX, -1)
            }
            Mv::Move(d, b) => {
                let d = d as usize;
                let a = self.assign[d] as usize;
                let s = self.dsz[d];
                let ea = self.e(a);
                let eb = self.e(b as usize);
                -lam * ((2 * s * (eb - ea) + 2 * s * s) as f64)
            }
            Mv::Insert(d, b) => {
                let d = d as usize;
                let s = self.dsz[d];
                let eb = self.e(b as usize);
                (self.dw[d] * s) as f64 / 1e6 - lam * ((2 * eb * s + s * s) as f64)
                    + self.pot(b as usize, eb + s, u32::MAX, u32::MAX, s) - self.pot(b as usize, eb, u32::MAX, u32::MAX, -1)
            }
            Mv::Swap(d1, d2) => {
                let (d1, d2) = (d1 as usize, d2 as usize);
                let a = self.assign[d1] as usize;
                let b = self.assign[d2] as usize;
                let (s1, s2) = (self.dsz[d1], self.dsz[d2]);
                if b == self.ns {
                    // d1 (dans a) <-> d2 libre
                    let dl = s2 - s1;
                    let ea = self.e(a);
                    (self.dw[d2] * s2 - self.dw[d1] * s1) as f64 / 1e6 - lam * ((2 * ea * dl + dl * dl) as f64)
                        + self.pot(a, ea + dl, d1 as u32, u32::MAX, s2) - self.pot(a, ea, u32::MAX, u32::MAX, -1)
                } else {
                    let dl = s2 - s1;
                    let ea = self.e(a);
                    let eb = self.e(b);
                    -lam * ((2 * dl * (ea - eb) + 2 * dl * dl) as f64)
                        + self.pot(a, ea + dl, d1 as u32, u32::MAX, s2) - self.pot(a, ea, u32::MAX, u32::MAX, -1)
                        + self.pot(b, eb - dl, d2 as u32, u32::MAX, s1) - self.pot(b, eb, u32::MAX, u32::MAX, -1)
                }
            }
            Mv::Cycle3Remove(..) => unreachable!(),
            Mv::SwapRemove(d1, d2, d3) => {
                let dsw = self.delta(Mv::Swap(d1, d2));
                let (d1, d2, d3) = (d1 as usize, d2 as usize, d3 as usize);
                let a = self.assign[d1] as usize;
                let ea2 = self.e(a) + self.dsz[d2] - self.dsz[d1];
                let s = self.dsz[d3];
                // potentiel de a : dsw contient déjà pot(après échange) - pot(avant) ; on remplace par pot(après retrait)
                dsw - (self.dw[d3] * s) as f64 / 1e6 - lam * ((s * s - 2 * ea2 * s) as f64)
                    - self.pot(a, ea2, d1 as u32, u32::MAX, self.dsz[d2])
                    + self.pot(a, ea2 - s, d1 as u32, d3 as u32, self.dsz[d2])
            }
        }
    }
    fn load(&mut self, assign: &[u32]) {
        for v in self.members.iter_mut() {
            v.clear();
        }
        for a in 0..self.ns {
            self.ssum[a] = 0;
        }
        self.cons_w = 0;
        self.cons_raw = 0;
        self.sum_e2 = 0;
        for d in 0..self.nd {
            let b = assign[d] as usize;
            self.assign[d] = b as u32;
            self.pos[d] = self.members[b].len() as u32;
            self.members[b].push(d as u32);
            if b < self.ns {
                self.ssum[b] += self.dsz[d];
                self.cons_w += self.dw[d] * self.dsz[d];
                self.cons_raw += self.dsz[d];
            }
        }
        for a in 0..self.ns {
            let e = self.e(a);
            self.sum_e2 += e * e;
        }
    }
    fn check(&self) -> bool {
        for a in 0..self.ns {
            let s: i64 = self.members[a].iter().map(|&d| self.dsz[d as usize]).sum();
            if s != self.ssum[a] || s < self.slb[a] || s > self.sub[a] {
                eprintln!("créneau {} somme {} [{}, {}]", a, s, self.slb[a], self.sub[a]);
                return false;
            }
            for &d in &self.members[a] {
                if self.dt[d as usize] != (self.st_of(a)) || (self.sfo[a] && !self.dfree[d as usize]) {
                    eprintln!("créneau {} dataset {} incompatible", a, d);
                    return false;
                }
            }
        }
        true
    }
    fn st_of(&self, a: usize) -> u8 {
        for t in 0..4 {
            if self.slots_by_type[t].binary_search(&(a as u32)).is_ok() {
                return t as u8;
            }
        }
        255
    }
}

fn lower_bound(v: &[i64], x: i64) -> usize {
    let (mut lo, mut hi) = (0usize, v.len());
    while lo < hi {
        let m = (lo + hi) / 2;
        if v[m] < x { lo = m + 1 } else { hi = m }
    }
    lo
}
fn upper_bound(v: &[i64], x: i64) -> usize {
    let (mut lo, mut hi) = (0usize, v.len());
    while lo < hi {
        let m = (lo + hi) / 2;
        if v[m] <= x { lo = m + 1 } else { hi = m }
    }
    lo
}

fn main() {
    let args: Vec<String> = env::args().collect();
    let inp = &args[1];
    let out = &args[2];
    let seed: u64 = args.get(3).map(|s| s.parse().unwrap()).unwrap_or(1);
    let tlim: f64 = args.get(4).map(|s| s.parse().unwrap()).unwrap_or(60.0);
    let tenure: u64 = args.get(5).map(|s| s.parse().unwrap()).unwrap_or(50);
    let lam: f64 = args.get(6).map(|s| s.parse().unwrap()).unwrap_or(1e-7);
    let ncand: usize = args.get(7).map(|s| s.parse().unwrap()).unwrap_or(64);
    let stagn: u64 = args.get(8).map(|s| s.parse().unwrap()).unwrap_or(300000);
    let pert: usize = args.get(9).map(|s| s.parse().unwrap()).unwrap_or(30);
    let mu: f64 = args.get(10).map(|s| s.parse().unwrap()).unwrap_or(0.0);

    let txt = fs::read_to_string(inp).expect("lecture");
    let mut it = txt.split_ascii_whitespace().map(|x| x.parse::<i64>().unwrap());
    let nd = it.next().unwrap() as usize;
    let ns = it.next().unwrap() as usize;
    let mut wf = [0i64; 4];
    let mut wc = [0i64; 4];
    for t in 0..4 { wf[t] = it.next().unwrap(); }
    for t in 0..4 { wc[t] = it.next().unwrap(); }
    let mut dt = vec![0u8; nd];
    let mut dsz = vec![0i64; nd];
    let mut dfree = vec![false; nd];
    let mut dw = vec![0i64; nd];
    let mut assign0 = vec![0u32; nd];
    for d in 0..nd {
        dt[d] = it.next().unwrap() as u8;
        dsz[d] = it.next().unwrap();
        dfree[d] = it.next().unwrap() == 1;
        let a = it.next().unwrap();
        assign0[d] = if a < 0 { ns as u32 } else { a as u32 };
        dw[d] = if dfree[d] { wf[dt[d] as usize] } else { wc[dt[d] as usize] };
    }
    let mut st = vec![0u8; ns];
    let mut slb = vec![0i64; ns];
    let mut sub = vec![0i64; ns];
    let mut sfo = vec![false; ns];
    for a in 0..ns {
        st[a] = it.next().unwrap() as u8;
        slb[a] = it.next().unwrap();
        sub[a] = it.next().unwrap();
        sfo[a] = it.next().unwrap() == 1;
        let _m = it.next().unwrap();
    }
    let mut by_type: [Vec<u32>; 4] = Default::default();
    let mut sizes: [Vec<i64>; 4] = Default::default();
    let mut slots_by_type: [Vec<u32>; 4] = Default::default();
    for d in 0..nd { by_type[dt[d] as usize].push(d as u32); }
    for t in 0..4 {
        by_type[t].sort_by_key(|&d| dsz[d as usize]);
        sizes[t] = by_type[t].iter().map(|&d| dsz[d as usize]).collect();
    }
    for a in 0..ns { slots_by_type[st[a] as usize].push(a as u32); }
    let total_size: i64 = dsz.iter().sum();
    let mut sys = Sys {
        nd, ns, dt, dsz, dfree, dw, slb, sub, sfo,
        ssum: vec![0; ns], members: vec![Vec::new(); ns + 1], pos: vec![0; nd], assign: vec![0; nd],
        by_type, sizes, slots_by_type, cons_w: 0, cons_raw: 0, sum_e2: 0, lam, mu,
    };
    sys.load(&assign0);
    if !sys.check() { eprintln!("solution de départ invalide"); std::process::exit(2); }
    let w0 = sys.cons_raw - sys.slb.iter().sum::<i64>();
    eprintln!("m3_tabu: {} datasets, {} créneaux, gaspillage {} ({:.3} %), f0 {:.2}, seed {} tenure {} lambda {:e} ncand {}",
        nd, ns, w0, 100.0 * w0 as f64 / total_size as f64, sys.f(), seed, tenure, lam, ncand);

    let mut rng = Rng(seed.wrapping_mul(0x9E3779B97F4A7C15) | 1);
    let mut tabu_until = vec![0u64; nd];
    let mut tabu_slot = vec![u32::MAX; nd];
    let mut best_w = sys.cons_w;
    let mut best_raw = sys.cons_raw;
    let mut best_assign = sys.assign.clone();
    let mut best_f = sys.f();
    let mut last_imp: u64 = 0;
    let mut iter: u64 = 0;
    let t0 = Instant::now();
    let logp: f64 = env::var("M3_LOG").ok().and_then(|x| x.parse().ok()).unwrap_or(10.0);
    let mut next_log = logp;
    let dbg = env::var("M3_DBG").is_ok();
    let cyc = env::var("M3_NOCYC").is_err();
    let pump = env::var("M3_NOPUMP").is_err();
    let minc: usize = env::var("M3_MINC").ok().and_then(|x| x.parse().ok()).unwrap_or(12);
    let mut n_pert = 0u64;
    let mut cands: Vec<(f64, Mv)> = Vec::with_capacity(ncand * 64);
    let mut emax: i64 = 1;
    let mut n_gen: u64 = 0;
    let mut n_app: u64 = 0;
    let mut kinds = [0u64; 6];

    loop {
        if iter & 255 == 0 {
            let el = t0.elapsed().as_secs_f64();
            if el > tlim { break; }
            if el > next_log {
                next_log += logp;
                let w = sys.cons_raw - sys.slb.iter().sum::<i64>();
                let bw = best_raw - sys.slb.iter().sum::<i64>();
                eprintln!("  t={:.0}s it={} ({:.0}/s) cand/it={:.1} appl={} emax={} cur gasp={} libres={} f={:.2} | best gasp={} ({:.3} %) consW={:.1} pert={} kinds={:?}",
                    el, iter, iter as f64 / el, n_gen as f64 / iter as f64, n_app, emax, w, sys.members[ns].len(), sys.f(), bw,
                    100.0 * bw as f64 / total_size as f64, best_w as f64 / 1e6, n_pert, kinds);
            }
        }
        iter += 1;
        if iter & 1023 == 1 {
            emax = 1;
            for a in 0..ns { let e = sys.e(a); if e > emax { emax = e; } }
        }
        cands.clear();
        let fcur = sys.f();
        for _ in 0..ncand {
            let r = rng.below(8);
            if r < 3 {
                // créneau a avec excès : retrait direct, ou échange d1<->d2 (pompe l'excès de b vers a) puis retrait de d3
                let a = rng.below(ns);
                let ea = sys.e(a);
                let na = sys.members[a].len();
                if na == 0 { continue; }
                let wa = sys.sub[a] - sys.slb[a];
                for i3 in 0..na {
                    let d3 = sys.members[a][i3] as usize;
                    let s3 = sys.dsz[d3];
                    let need = s3 - ea;
                    if need <= 0 {
                        n_gen += 1;
                        cands.push((sys.delta(Mv::Remove(d3 as u32)), Mv::Remove(d3 as u32)));
                        continue;
                    }
                    if s3 > wa { continue; }
                    for i1 in 0..na {
                        if i1 == i3 { continue; }
                        let d1 = sys.members[a][i1] as usize;
                        let s1 = sys.dsz[d1];
                        let t = sys.dt[d1] as usize;
                        let sz = &sys.sizes[t];
                        let lo = lower_bound(sz, s1 + need);
                        let hi = upper_bound(sz, s1 + (wa - ea).min(emax));
                        if lo >= hi { continue; }
                        let n = hi - lo;
                        let step = if n > 48 { n / 48 + 1 } else { 1 };
                        let mut j = lo + if step > 1 { rng.below(step) } else { 0 };
                        while j < hi {
                            let d2 = sys.by_type[t][j] as usize;
                            j += step;
                            let b = sys.assign[d2] as usize;
                            if b == a { continue; }
                            if sys.sfo[a] && !sys.dfree[d2] { continue; }
                            let dl = sys.dsz[d2] - s1;
                            if b < ns {
                                if sys.sfo[b] && !sys.dfree[d1] { continue; }
                                if sys.e(b) < dl { continue; }
                            }
                            n_gen += 1;
                            let mv = Mv::SwapRemove(d1 as u32, d2 as u32, d3 as u32);
                            cands.push((sys.delta(mv), mv));
                        }
                    }
                }
            } else if r == 4 && cyc {
                // chaîne d'éjection : d1: A->B, d2: B->C, d2p: C->A puis retrait d3 (A)
                let a = rng.below(ns);
                let ea = sys.e(a);
                let na = sys.members[a].len();
                if na < 2 { continue; }
                let wa = sys.sub[a] - sys.slb[a];
                for i3 in 0..na {
                    let d3 = sys.members[a][i3] as usize;
                    let s3 = sys.dsz[d3];
                    let need = s3 - ea;
                    if need <= 0 || s3 > wa { continue; }
                    for i1 in 0..na {
                        if i1 == i3 { continue; }
                        let d1 = sys.members[a][i1] as usize;
                        let s1 = sys.dsz[d1];
                        let t = sys.dt[d1] as usize;
                        let lo = lower_bound(&sys.sizes[t], s1 + need);
                        let hi = upper_bound(&sys.sizes[t], s1 + (wa - ea).min(2 * emax));
                        if lo >= hi { continue; }
                        for _ in 0..12 {
                            let d2p = sys.by_type[t][lo + rng.below(hi - lo)] as usize;
                            let c = sys.assign[d2p] as usize;
                            if c == a { continue; }
                            if sys.sfo[a] && !sys.dfree[d2p] { continue; }
                            let s2p = sys.dsz[d2p];
                            let ec = if c < ns { sys.e(c) } else { 1 << 40 };
                            let lo2 = lower_bound(&sys.sizes[t], s2p - ec);
                            let hi2 = upper_bound(&sys.sizes[t], s1 + emax);
                            if lo2 >= hi2 { continue; }
                            for _ in 0..6 {
                                let d2 = sys.by_type[t][lo2 + rng.below(hi2 - lo2)] as usize;
                                let b = sys.assign[d2] as usize;
                                if b == a || b == c || d2 == d1 || d2 == d2p { continue; }
                                if b < ns && (sys.sfo[b] && !sys.dfree[d1]) { continue; }
                                if c < ns && (sys.sfo[c] && !sys.dfree[d2]) { continue; }
                                let s2 = sys.dsz[d2];
                                if b < ns && (sys.e(b) < s2 - s1 || sys.e(b) + s1 - s2 > sys.sub[b] - sys.slb[b]) { continue; }
                                if c < ns && (ec < s2p - s2 || ec + s2 - s2p > sys.sub[c] - sys.slb[c]) { continue; }
                                // tabou : vérifié ici (sinon la sélection ne sait pas)
                                if (tabu_until[d1] > iter && tabu_slot[d1] == b as u32) || (tabu_until[d2] > iter && tabu_slot[d2] == c as u32)
                                    || (tabu_until[d2p] > iter && tabu_slot[d2p] == a as u32) { continue; }
                                if let Some(df) = sys.delta_cycle(d1 as u32, d2 as u32, d2p as u32, d3 as u32) {
                                    n_gen += 1;
                                    cands.push((df, Mv::Cycle3Remove(d1 as u32, d2 as u32, d2p as u32, d3 as u32)));
                                }
                            }
                        }
                    }
                }
            } else if r == 5 && pump {
                // pompage : échanges qui augmentent l'excès d'un créneau a proche d'un retrait (besoin <= emax)
                let a = rng.below(ns);
                let ea = sys.e(a);
                let na = sys.members[a].len();
                if na < 2 { continue; }
                let wa = sys.sub[a] - sys.slb[a];
                let mut need = i64::MAX;
                for &d in &sys.members[a] {
                    let sz = sys.dsz[d as usize];
                    if sz <= wa && sz - ea < need { need = sz - ea; }
                }
                if need <= 0 || need > emax { continue; }
                for i1 in 0..na {
                    let d1 = sys.members[a][i1] as usize;
                    let s1 = sys.dsz[d1];
                    let t = sys.dt[d1] as usize;
                    let lo = lower_bound(&sys.sizes[t], s1 + 1);
                    let hi = upper_bound(&sys.sizes[t], s1 + need.min(wa - ea));
                    if lo >= hi { continue; }
                    for _ in 0..8 {
                        let d2 = sys.by_type[t][lo + rng.below(hi - lo)] as usize;
                        let b = sys.assign[d2] as usize;
                        if b == a || b == ns { continue; }
                        if (sys.sfo[a] && !sys.dfree[d2]) || (sys.sfo[b] && !sys.dfree[d1]) { continue; }
                        let dl = sys.dsz[d2] - s1;
                        if sys.e(b) < dl { continue; }
                        n_gen += 1;
                        cands.push((sys.delta(Mv::Swap(d1 as u32, d2 as u32)), Mv::Swap(d1 as u32, d2 as u32)));
                    }
                }
            } else if r == 3 {
                // insertion depuis P (rare) ou échange avec P
                let pl = sys.members[ns].len();
                if pl == 0 { continue; }
                let p = sys.members[ns][rng.below(pl)] as usize;
                let s = sys.dsz[p];
                let t = sys.dt[p] as usize;
                let sl = &sys.slots_by_type[t];
                let b = sl[rng.below(sl.len())] as usize;
                if sys.sfo[b] && !sys.dfree[p] { continue; }
                if sys.room(b) >= s {
                    cands.push((sys.delta(Mv::Insert(p as u32, b as u32)), Mv::Insert(p as u32, b as u32)));
                }
                // échange p <-> d1 dans b : s1 in [s - room_b, s + e_b]
                if sys.members[b].is_empty() { continue; }
                let d1 = sys.members[b][rng.below(sys.members[b].len())] as usize;
                let dl = s - sys.dsz[d1];
                let eb = sys.e(b);
                if eb + dl >= 0 && eb + dl <= sys.sub[b] - sys.slb[b] {
                    cands.push((sys.delta(Mv::Swap(d1 as u32, p as u32)), Mv::Swap(d1 as u32, p as u32)));
                }
            } else {
                // échange d1 (créneau a) <-> d2 (créneau b ou P) : énumération des partenaires de taille
                // s2 in [s1 - e_a, s1 + emax] (faisable ssi delta = s2 - s1 in [-e_a, e_b] à fenêtres larges)
                let d1 = rng.below(nd);
                let a = sys.assign[d1] as usize;
                if a == ns { continue; }
                let s1 = sys.dsz[d1];
                let t = sys.dt[d1] as usize;
                let ea = sys.e(a);
                let ra = sys.room(a);
                let sz = &sys.sizes[t];
                let lo = lower_bound(sz, s1 - ea);
                let hi = upper_bound(sz, s1 + emax.min(ra));
                if lo >= hi { continue; }
                let n = hi - lo;
                let step = if n > 192 { n / 192 + 1 } else { 1 };
                let off = if step > 1 { rng.below(step) } else { 0 };
                let mut j = lo + off;
                while j < hi {
                    let d2 = sys.by_type[t][j] as usize;
                    j += step;
                    if d2 == d1 { continue; }
                    let b = sys.assign[d2] as usize;
                    if b == a { continue; }
                    if sys.sfo[a] && !sys.dfree[d2] { continue; }
                    let s2 = sys.dsz[d2];
                    let dl = s2 - s1;
                    if b < ns {
                        if sys.sfo[b] && !sys.dfree[d1] { continue; }
                        let eb = sys.e(b);
                        if eb - dl < 0 || eb - dl > sys.sub[b] - sys.slb[b] { continue; }
                    }
                    n_gen += 1;
                    cands.push((sys.delta(Mv::Swap(d1 as u32, d2 as u32)), Mv::Swap(d1 as u32, d2 as u32)));
                }
            }
        }
        if cands.is_empty() { continue; }
        // choix du meilleur non tabou (aspiration si record de f)
        let mut best: Option<(f64, Mv)> = None;
        for &(df, mv) in &cands {
            let tabu = match mv {
                Mv::Remove(d) => tabu_until[d as usize] > iter && tabu_slot[d as usize] == ns as u32,
                Mv::Move(d, b) | Mv::Insert(d, b) => tabu_until[d as usize] > iter && tabu_slot[d as usize] == b,
                Mv::Cycle3Remove(..) => false,
                Mv::Swap(d1, d2) | Mv::SwapRemove(d1, d2, _) => {
                    let a = sys.assign[d1 as usize];
                    let b = sys.assign[d2 as usize];
                    (tabu_until[d1 as usize] > iter && tabu_slot[d1 as usize] == b)
                        || (tabu_until[d2 as usize] > iter && tabu_slot[d2 as usize] == a)
                }
            };
            if tabu && fcur + df >= best_f - 1e-9 { continue; }
            if best.map_or(true, |(bd, _)| df < bd) { best = Some((df, mv)); }
        }
        let Some((bdf, mv)) = best else { continue; };
        if bdf > 0.0 && cands.len() < minc { continue; }
        if dbg { match mv { Mv::Remove(d) | Mv::Insert(d, _) => eprintln!("it {} {:?} delta {:.3} ncand {} s={} e_a={} f={:.3}", iter, mv, bdf, cands.len(), sys.dsz[d as usize], if (sys.assign[d as usize] as usize) < ns { sys.e(sys.assign[d as usize] as usize) } else { -1 }, sys.f()), _ => {} } }
        let until = iter + tenure + rng.below((tenure / 2 + 1) as usize) as u64;
        match mv {
            Mv::Remove(d) | Mv::Move(d, _) | Mv::Insert(d, _) => {
                tabu_until[d as usize] = until;
                tabu_slot[d as usize] = sys.assign[d as usize];
            }
            Mv::Swap(d1, d2) => {
                tabu_until[d1 as usize] = until;
                tabu_slot[d1 as usize] = sys.assign[d1 as usize];
                tabu_until[d2 as usize] = until;
                tabu_slot[d2 as usize] = sys.assign[d2 as usize];
            }
            Mv::Cycle3Remove(d1, d2, d2p, d3) => {
                for d in [d1, d2, d2p, d3] {
                    tabu_until[d as usize] = until;
                    tabu_slot[d as usize] = sys.assign[d as usize];
                }
            }
            Mv::SwapRemove(d1, d2, d3) => {
                tabu_until[d1 as usize] = until;
                tabu_slot[d1 as usize] = sys.assign[d1 as usize];
                tabu_until[d2 as usize] = until;
                tabu_slot[d2 as usize] = sys.assign[d2 as usize];
                tabu_until[d3 as usize] = until;
                tabu_slot[d3 as usize] = sys.assign[d3 as usize];
            }
        }
        sys.apply(mv);
        n_app += 1;
        kinds[match mv { Mv::Remove(_) => 0, Mv::Move(..) => 1, Mv::Insert(..) => 2, Mv::Swap(..) => 3, Mv::SwapRemove(..) => 4, Mv::Cycle3Remove(..) => 5 }] += 1;
        let f = sys.f();
        if f < best_f { best_f = f; }
        if sys.cons_w < best_w {
            best_w = sys.cons_w;
            best_raw = sys.cons_raw;
            best_assign.copy_from_slice(&sys.assign);
            last_imp = iter;
        }
        if iter - last_imp > stagn {
            // redémarrage depuis le record + perturbation aléatoire (échanges faisables quelconques)
            sys.load(&best_assign);
            n_pert += 1;
            let mut done = 0;
            let mut tries = 0;
            while done < pert && tries < pert * 200 {
                tries += 1;
                let d1 = rng.below(nd);
                let a = sys.assign[d1] as usize;
                if a == ns { continue; }
                let s1 = sys.dsz[d1];
                let t = sys.dt[d1] as usize;
                let sz = &sys.sizes[t];
                let lo = lower_bound(sz, s1 - sys.e(a));
                let hi = upper_bound(sz, s1 + sys.room(a));
                if lo >= hi { continue; }
                let d2 = sys.by_type[t][lo + rng.below(hi - lo)] as usize;
                if d2 == d1 { continue; }
                let b = sys.assign[d2] as usize;
                if b == a || b == ns { continue; }
                if (sys.sfo[a] && !sys.dfree[d2]) || (sys.sfo[b] && !sys.dfree[d1]) { continue; }
                let dl = sys.dsz[d2] - s1;
                let eb = sys.e(b);
                if eb - dl < 0 || eb - dl > sys.sub[b] - sys.slb[b] { continue; }
                sys.apply(Mv::Swap(d1 as u32, d2 as u32));
                done += 1;
            }
            best_f = sys.f().min(best_f);
            last_imp = iter;
        }
    }
    sys.load(&best_assign);
    if !sys.check() { eprintln!("ERREUR : record invalide"); std::process::exit(2); }
    let bw = best_raw - sys.slb.iter().sum::<i64>();
    eprintln!("FIN it={} gaspillage {} -> {} ({:.3} %) libres {} consW {:.1}", iter, w0, bw,
        100.0 * bw as f64 / total_size as f64, sys.members[ns].len(), best_w as f64 / 1e6);
    let mut f = fs::File::create(out).expect("sortie");
    let mut s = String::with_capacity(nd * 6);
    for d in 0..nd {
        let a = sys.assign[d];
        s.push_str(&(if a == ns as u32 { -1i64 } else { a as i64 }).to_string());
        s.push('\n');
    }
    f.write_all(s.as_bytes()).unwrap();
}
