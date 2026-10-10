"""MINI RTS v2 - logique du jeu (sans interface)."""
import heapq
import math
import random

MAP_W, MAP_H = 2400, 1600
POP_MAX = 40
VIEW_H = 640
CELL = 40
GW, GH = MAP_W // CELL, MAP_H // CELL
NB = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
      (1, 1, 1.414), (1, -1, 1.414), (-1, 1, 1.414), (-1, -1, 1.414)]

# cost = (bois, minerai) ; time = secondes de production
UNITS = {
    'worker': dict(label='Récolteur', hp=40, speed=90, dmg=3, rng=18, cd=1.0, cost=(50, 0), time=5, r=11, armor=0),
    'soldier': dict(label='Soldat', hp=110, speed=78, dmg=12, rng=24, cd=0.9, cost=(50, 25), time=8, r=13, armor=2),
    'archer': dict(label='Archer', hp=50, speed=85, dmg=9, rng=140, cd=1.1, cost=(50, 30), time=8, r=11, armor=0),
    'knight': dict(label='Cavalier', hp=120, speed=135, dmg=16, rng=26, cd=1.0, cost=(80, 60), time=12, r=16, armor=1),
}
# time = secondes de travail d'un récolteur
BUILDINGS = {
    'hq': dict(label='QG', hp=1000, r=58, cost=(0, 0), time=0, makes=['worker']),
    'barracks': dict(label='Caserne', hp=500, r=44, cost=(150, 50), time=14, makes=['soldier', 'archer']),
    'stable': dict(label='Écurie', hp=500, r=44, cost=(180, 100), time=16, makes=['knight']),
    'depot': dict(label='Dépôt', hp=260, r=34, cost=(100, 0), time=8, makes=[]),
    'tower': dict(label='Tour', hp=320, r=26, cost=(120, 60), time=12, makes=[], dmg=11, rng=200, cd=1.2),
}
# triangle : soldat > cavalier > archer > soldat
BONUS = {('soldier', 'knight'): 1.5, ('knight', 'archer'): 1.6, ('archer', 'soldier'): 1.5}
BUILD_MULT = {'archer': 0.4, 'knight': 0.8}
AI_GATHER = (0.8, 1.0, 1.3)
AI_THINK = (1.4, 1.0, 0.6)
AI_GRACE = (300, 210, 140)      # pas d'attaque avant ce délai (s)
DIFF_NAMES = ('Facile', 'Normal', 'Difficile')


def dist(ax, ay, bx, by):
    return math.hypot(ax - bx, ay - by)


class Res:
    def __init__(self, kind, x, y, amount):
        self.kind, self.x, self.y, self.amount, self.max = kind, x, y, amount, amount
        self.r = 14 if kind == 'wood' else 16


class Ent:
    def __init__(self, kind, team, x, y, building=False, done=True):
        self.d = (BUILDINGS if building else UNITS)[kind]
        self.kind, self.team, self.x, self.y, self.b = kind, team, x, y, building
        self.maxhp = self.d['hp']
        self.hp = self.maxhp if done else self.maxhp * 0.2
        self.r = self.d['r']
        self.dead = False
        self.mode = 'idle'      # idle / move / amove / attack / harvest / build
        self.dest = None
        self.target = None
        self.resume = None
        self.prev = None
        self.auto = False
        self.home = (x, y)
        self.cd = 0.0
        self.flash = 0.0
        self.carry = 0
        self.ctype = None
        self.hs = 'go'
        self.gt = 0.0
        self.st = 0.0
        self.lr = 1e9
        self.ang = random.uniform(-3, 3)
        self.moving = False
        self.working = False
        self.built = done
        self.bt = 0.0
        self.queue = []
        self.qt = 0.0
        self.rally = None


class Game:
    def __init__(self):
        self.diff = 1
        self.reset()

    # ------------------------------------------------------------ carte
    def reset(self):
        self.ents, self.res, self.rocks, self.fx = [], [], [], []
        self.stock = {0: {'wood': 200, 'ore': 100}, 1: {'wood': 200, 'ore': 100}}
        self.bases = {0: (320, 1250), 1: (2080, 350)}
        self.cam = [0, MAP_H - VIEW_H]
        self.sel, self.placing, self.drag = [], None, None
        self.over, self.paused, self.amove = None, False, False
        self.time = 0.0
        self.msg, self.msg_t = '', 0.0
        self.obst = []
        self.aist = {t: dict(t=0.0, wave_n=[6, 5, 4][self.diff], wave=set(), wave_size=0) for t in (0, 1)}
        for t, (bx, by) in self.bases.items():
            self.ents.append(Ent('hq', t, bx, by, True))
            for i in range(3):
                self.ents.append(Ent('worker', t, bx - 40 + i * 24, by + 75 * (1 if t == 0 else -1)))
            self.ents.append(Ent('soldier', t, bx + 50, by + 75 * (1 if t == 0 else -1)))
        for _ in range(500):
            if len(self.rocks) >= 24:
                break
            x, y, r = random.randint(100, MAP_W - 100), random.randint(100, MAP_H - 100), random.randint(20, 42)
            if all(dist(x, y, bx, by) > 330 for bx, by in self.bases.values()) and self.free(x, y, r, 40):
                self.rocks.append((x, y, r))
        for t, (bx, by) in self.bases.items():
            s = 1 if t == 0 else -1
            self.patch('wood', bx + 250 * s, by - 90 * s, 8, 80, 300)
            self.patch('ore', bx - 60 * s, by - 240 * s, 4, 55, 450)
            self.patch('wood', bx - 120 * s, by + 170 * s, 6, 70, 300)
        for cx, cy in ((1200, 800), (850, 520), (1550, 1080), (700, 1050), (1700, 560)):
            self.patch('wood', cx, cy, 7, 85, 300)
        for cx, cy in ((1200, 430), (1200, 1170), (1000, 800), (1400, 800)):
            self.patch('ore', cx, cy, 3, 50, 450)
        self.rebuild_obst()

    def patch(self, kind, cx, cy, n, rad, amount):
        placed = 0
        for _ in range(300):
            if placed >= n:
                break
            a, d = random.uniform(0, 6.283), random.uniform(0, rad)
            x, y = cx + math.cos(a) * d, cy + math.sin(a) * d
            if self.free(x, y, 16, 2):
                self.res.append(Res(kind, x, y, amount))
                placed += 1

    def rebuild_obst(self):
        self.obst = [(e.x, e.y, e.r) for e in self.ents if e.b and not e.dead]
        self.obst += [(r.x, r.y, r.r) for r in self.res] + list(self.rocks)
        blk = bytearray(GW * GH)
        for ox, oy, orr in self.obst:
            rad = orr + 22
            for cy in range(max(0, int((oy - rad) // CELL)), min(GH, int((oy + rad) // CELL) + 1)):
                for cx in range(max(0, int((ox - rad) // CELL)), min(GW, int((ox + rad) // CELL) + 1)):
                    if dist((cx + .5) * CELL, (cy + .5) * CELL, ox, oy) < rad:
                        blk[cx + cy * GW] = 1
        self.blk = blk
        self.fcache = {}

    # --- recherche de chemin : champ de distance (Dijkstra) mis en cache par objectif
    def field(self, gx, gy):
        key = (gx, gy)
        f = self.fcache.get(key)
        if f is not None:
            return f
        if len(self.fcache) > 60:
            self.fcache.clear()
        INF = 1e9
        blk = self.blk
        f = [INF] * (GW * GH)
        g = gx + gy * GW
        f[g] = 0.0
        h = [(0.0, g)]
        while h:
            d, i = heapq.heappop(h)
            if d > f[i]:
                continue
            x, y = i % GW, i // GW
            for dx, dy, c in NB:
                nx, ny = x + dx, y + dy
                if nx < 0 or ny < 0 or nx >= GW or ny >= GH:
                    continue
                j = nx + ny * GW
                if blk[j] and (nx - gx) ** 2 + (ny - gy) ** 2 > 4:
                    continue
                if dx and dy and (blk[nx + y * GW] or blk[x + ny * GW]):
                    continue
                nd = d + c
                if nd < f[j]:
                    f[j] = nd
                    heapq.heappush(h, (nd, j))
        self.fcache[key] = f
        return f

    def clear(self, x0, y0, x1, y1):
        d = dist(x0, y0, x1, y1)
        n = max(1, int(d // 20))
        for k in range(n + 1):
            t = k / n
            cx, cy = int((x0 + (x1 - x0) * t) // CELL), int((y0 + (y1 - y0) * t) // CELL)
            if 0 <= cx < GW and 0 <= cy < GH and self.blk[cx + cy * GW]:
                return False
        return True

    def flow_dir(self, u, tx, ty):
        gx, gy = min(GW - 1, max(0, int(tx // CELL))), min(GH - 1, max(0, int(ty // CELL)))
        f = self.field(gx, gy)
        cx, cy = min(GW - 1, max(0, int(u.x // CELL))), min(GH - 1, max(0, int(u.y // CELL)))
        aim = None
        for _ in range(3):                      # on vise jusqu'à 3 cases plus loin (si ligne dégagée)
            bd, best = f[cx + cy * GW], None
            for dx, dy, c in NB:
                nx, ny = cx + dx, cy + dy
                if 0 <= nx < GW and 0 <= ny < GH and f[nx + ny * GW] < bd - 1e-6:
                    bd, best = f[nx + ny * GW], (nx, ny)
            if best is None:
                break
            px, py = (best[0] + .5) * CELL, (best[1] + .5) * CELL
            if aim is not None and not self.clear(u.x, u.y, px, py):
                break
            aim = (px, py)
            cx, cy = best
        if aim is None:
            return None
        d = dist(u.x, u.y, aim[0], aim[1])
        if d < 1:
            return None
        return (aim[0] - u.x) / d, (aim[1] - u.y) / d

    # ------------------------------------------------------------ utilitaires
    def say(self, text):
        self.msg, self.msg_t = text, 2.5

    def free(self, x, y, r, pad=6):
        if x < r or y < r or x > MAP_W - r or y > MAP_H - r:
            return False
        for o in self.ents:
            if o.b and not o.dead and dist(o.x, o.y, x, y) < o.r + r + pad:
                return False
        for o in self.res:
            if dist(o.x, o.y, x, y) < o.r + r + pad:
                return False
        for ox, oy, orr in self.rocks:
            if dist(ox, oy, x, y) < orr + r + pad:
                return False
        return True

    def pop(self, team):
        return sum(1 for e in self.ents if e.team == team and not e.b and not e.dead)

    def mil(self, team):
        return [e for e in self.ents if e.team == team and not e.b and e.kind != 'worker' and not e.dead]

    def nearest_enemy(self, u, rad, units_only=False):
        best, bd = None, rad
        for e in self.ents:
            if e.team != u.team and not e.dead and not (units_only and e.b):
                d = dist(u.x, u.y, e.x, e.y) - e.r
                if d < bd:
                    best, bd = e, d
        return best

    def nearest_res(self, x, y, kind):
        best, bd = None, 1e9
        for r in self.res:
            if r.kind == kind and r.amount > 0:
                d = dist(x, y, r.x, r.y)
                if d < bd:
                    best, bd = r, d
        return best

    def nearest_drop(self, u):
        best, bd = None, 1e9
        for e in self.ents:
            if e.team == u.team and e.b and e.built and e.kind in ('hq', 'depot') and not e.dead:
                d = dist(u.x, u.y, e.x, e.y)
                if d < bd:
                    best, bd = e, d
        return best

    def puff(self, x, y, col, n=6, speed=60, life=0.5, size=3):
        for _ in range(n):
            a, s = random.uniform(0, 6.283), random.uniform(0.3, 1) * speed
            self.fx.append(dict(t='p', x=x, y=y, vx=math.cos(a) * s, vy=math.sin(a) * s,
                                life=life, max=life, col=col, size=size))
        if len(self.fx) > 250:
            del self.fx[:60]

    # ------------------------------------------------------------ actions
    def affordable(self, team, cost):
        st = self.stock[team]
        return st['wood'] >= cost[0] and st['ore'] >= cost[1]

    def queue(self, b, kind):
        if not b.built or kind not in b.d['makes'] or len(b.queue) >= 5:
            return False
        c = UNITS[kind]['cost']
        if not self.affordable(b.team, c):
            return False
        st = self.stock[b.team]
        st['wood'] -= c[0]
        st['ore'] -= c[1]
        b.queue.append(kind)
        return True

    def cancel(self, b):
        if b.queue:
            c = UNITS[b.queue.pop()]['cost']
            st = self.stock[b.team]
            st['wood'] += c[0]
            st['ore'] += c[1]
            if not b.queue:
                b.qt = 0.0

    def can_place(self, team, kind, x, y):
        if not self.free(x, y, BUILDINGS[kind]['r'], 8):
            return False
        return any(e.b and e.built and e.team == team and not e.dead and dist(e.x, e.y, x, y) < 450
                   for e in self.ents)

    def place(self, team, kind, x, y):
        c = BUILDINGS[kind]['cost']
        if not self.affordable(team, c) or not self.can_place(team, kind, x, y):
            return None
        st = self.stock[team]
        st['wood'] -= c[0]
        st['ore'] -= c[1]
        b = Ent(kind, team, x, y, True, done=False)
        self.ents.append(b)
        self.rebuild_obst()
        return b

    def order_move(self, u, x, y):
        u.mode, u.dest, u.target, u.auto, u.resume, u.lr, u.st = 'move', (x, y), None, False, None, 1e9, 0.0

    def order_amove(self, u, x, y):
        u.mode, u.dest, u.target, u.auto, u.resume, u.lr, u.st = 'amove', (x, y), None, False, None, 1e9, 0.0

    def order_harvest(self, u, r):
        if u.carry and u.ctype != r.kind:
            u.carry = 0
        u.mode, u.target, u.ctype, u.hs, u.auto, u.resume = 'harvest', r, r.kind, 'go', False, None

    def order_attack(self, u, t, auto=False):
        u.mode, u.target, u.auto, u.home, u.resume = 'attack', t, auto, (u.x, u.y), None

    def order_build(self, u, b):
        if u.mode == 'harvest' and isinstance(u.target, Res):
            u.prev = u.target
        u.mode, u.target, u.auto, u.resume = 'build', b, False, None

    def stop(self, u):
        u.mode, u.target, u.resume, u.prev = 'idle', None, None, None

    def start_place(self, kind):
        if not self.affordable(0, BUILDINGS[kind]['cost']):
            self.say('Ressources insuffisantes')
        else:
            self.placing = kind

    def build_with_selected(self, kind, x, y):
        b = self.place(0, kind, x, y)
        if not b:
            return False
        ws = [e for e in self.sel if e.team == 0 and e.kind == 'worker']
        if not ws:
            ws = sorted([e for e in self.ents if e.team == 0 and e.kind == 'worker'],
                        key=lambda e: dist(e.x, e.y, x, y))[:1]
        for w in ws:
            self.order_build(w, b)
        return True

    def produce(self, kind):
        cands = [e for e in self.sel if e.team == 0 and e.b and e.built and kind in e.d['makes']]
        if not cands:
            return
        b = min(cands, key=lambda e: len(e.queue))
        if not self.queue(b, kind):
            self.say('Ressources insuffisantes ou file pleine')

    def cancel_selected(self):
        for e in self.sel:
            if e.team == 0 and e.b and e.queue:
                self.cancel(e)
                break

    # ------------------------------------------------------------ combat
    def strike(self, a, t):
        d = a.d
        mult = BONUS.get((a.kind, t.kind), 1.0)
        if t.b:
            mult *= BUILD_MULT.get(a.kind, 1.0)
        dmg = max(1.0, d['dmg'] * mult - (0 if t.b else t.d.get('armor', 0)))
        t.hp -= dmg
        a.cd, a.flash = d['cd'], 0.15
        a.ang = math.atan2(t.y - a.y, t.x - a.x)
        if d['rng'] > 60:
            self.fx.append(dict(t='a', x=a.x, y=a.y, x1=t.x, y1=t.y, life=0.22, max=0.22))
        else:
            self.puff(t.x, t.y, (1, 0.9, 0.5), 3, 40, 0.25, 2)
        if t.hp <= 0 and not t.dead:
            t.dead = True
            self.puff(t.x, t.y, (0.8, 0.8, 0.8) if t.b else (0.9, 0.3, 0.3), 16 if t.b else 8, 90, 0.7, 4)
            if t.b:
                self.rebuild_obst()

    # ------------------------------------------------------------ déplacement
    def avoid(self, u, dx, dy, tx, ty):
        best_t, best = 1e9, None
        for ox, oy, orr in self.obst:
            if abs(ox - tx) < 1 and abs(oy - ty) < 1:
                continue
            rx, ry = ox - u.x, oy - u.y
            t = rx * dx + ry * dy
            rr = orr + u.r + 6
            if t <= 0 or t > 50 + rr or t >= best_t:
                continue
            pd = math.hypot(rx - dx * t, ry - dy * t)
            if pd < rr:
                best_t, best = t, (rx, ry, (rr - pd) / rr)
        if best:
            rx, ry, k = best
            side = 1 if dx * ry - dy * rx > 0 else -1
            a = -side * (0.8 + 0.7 * k)
            c, s = math.cos(a), math.sin(a)
            return dx * c - dy * s, dx * s + dy * c
        return dx, dy

    def step(self, u, tx, ty, dt, stop=0):
        d = dist(u.x, u.y, tx, ty)
        if d - stop <= 0.5:
            u.moving = False
            return 0
        dx, dy = (tx - u.x) / d, (ty - u.y) / d
        L = min(d, 200)
        if not self.clear(u.x, u.y, u.x + dx * L, u.y + dy * L):
            v = self.flow_dir(u, tx, ty)
            if v:
                dx, dy = v
        dx, dy = self.avoid(u, dx, dy, tx, ty)
        m = min(u.d['speed'] * dt, d - stop)
        u.x += dx * m
        u.y += dy * m
        u.ang = math.atan2(dy, dx)
        u.moving = True
        return max(0, dist(u.x, u.y, tx, ty) - stop)

    def acquire_range(self, u):
        return max(190, u.d['rng'] + 50)

    def after_attack(self, u):
        u.target = None
        if u.resume:
            u.mode, u.dest, u.resume, u.lr, u.st = 'amove', u.resume, None, 1e9, 0.0
        else:
            u.mode = 'idle'

    def upd_unit(self, u, dt):
        u.cd = max(0, u.cd - dt)
        u.flash = max(0, u.flash - dt)
        u.moving = u.working = False
        if u.mode == 'idle' and u.kind != 'worker':
            t = self.nearest_enemy(u, self.acquire_range(u))
            if t:
                self.order_attack(u, t, auto=True)
        if u.mode == 'move':
            self.go(u, dt)
        elif u.mode == 'amove':
            t = self.nearest_enemy(u, self.acquire_range(u)) if u.kind != 'worker' else None
            if t:
                keep = u.dest
                self.order_attack(u, t, auto=True)
                u.resume = keep
            else:
                self.go(u, dt)
        elif u.mode == 'attack':
            t = u.target
            if t is None or t.dead:
                self.after_attack(u)
                return
            if t.b:
                n = self.nearest_enemy(u, u.d['rng'] + 70, units_only=True)
                if n:
                    u.target = t = n
            if u.auto and dist(u.x, u.y, u.home[0], u.home[1]) > 320:
                self.after_attack(u)
                return
            d = dist(u.x, u.y, t.x, t.y) - t.r - u.r
            if d <= u.d['rng']:
                u.ang = math.atan2(t.y - u.y, t.x - u.x)
                if u.cd <= 0:
                    self.strike(u, t)
            else:
                self.step(u, t.x, t.y, dt, stop=t.r + u.r + u.d['rng'] * 0.85)
        elif u.mode == 'harvest':
            self.harvest(u, dt)
        elif u.mode == 'build':
            self.construct(u, dt)

    def go(self, u, dt):
        rem = self.step(u, u.dest[0], u.dest[1], dt)
        u.st += dt
        if u.st >= 1.0:              # bloqué ?
            if u.lr - rem < 8:
                rem = 0
            u.lr, u.st = rem, 0.0
        if rem <= 2:
            u.mode = 'idle'

    def construct(self, u, dt):
        b = u.target
        if b is None or b.dead or b.built:
            u.mode, u.target = 'idle', None
            if u.prev and u.prev.amount > 0:
                self.order_harvest(u, u.prev)
            u.prev = None
            return
        if self.step(u, b.x, b.y, dt, stop=b.r + u.r + 3) <= 1:
            u.working = True
            u.ang = math.atan2(b.y - u.y, b.x - u.x)
            b.bt += dt
            b.hp = min(b.maxhp, b.hp + b.maxhp * 0.8 / b.d['time'] * dt)
            if b.bt >= b.d['time']:
                b.built, b.hp = True, b.maxhp
                self.puff(b.x, b.y, (1, 0.9, 0.6), 14, 80, 0.7, 4)

    def harvest(self, u, dt):
        r = u.target
        if u.hs != 'return' and (r is None or r.amount <= 0):
            r = u.target = self.nearest_res(u.x, u.y, u.ctype or 'wood')
            if r is None:
                if u.carry > 0:
                    u.hs = 'return'
                else:
                    u.mode = 'idle'
                    return
        if u.hs == 'go':
            if self.step(u, r.x, r.y, dt, stop=r.r + u.r + 2) <= 1:
                u.hs, u.gt = 'gather', 0.0
        elif u.hs == 'gather':
            u.working = True
            u.ang = math.atan2(r.y - u.y, r.x - u.x)
            u.gt += dt
            if u.gt >= 1.0:
                u.gt = 0.0
                take = min(5, r.amount, 10 - u.carry)
                r.amount -= take
                u.carry += take
                if u.carry >= 10 or r.amount <= 0:
                    u.hs = 'return'
        elif u.hs == 'return':
            b = self.nearest_drop(u)
            if b is None:
                u.mode = 'idle'
                return
            if self.step(u, b.x, b.y, dt, stop=b.r + u.r + 2) <= 1:
                k = AI_GATHER[self.diff] if u.team == 1 else 1.0
                self.stock[u.team][u.ctype] += int(round(u.carry * k))
                u.carry, u.hs = 0, 'go'

    def upd_building(self, b, dt):
        if not b.built:
            return
        if b.kind == 'tower':
            b.cd = max(0, b.cd - dt)
            b.flash = max(0, b.flash - dt)
            if b.cd <= 0:
                t = self.nearest_enemy(b, b.d['rng'], units_only=True)
                if t:
                    self.strike(b, t)
        if b.queue:
            k = b.queue[0]
            b.qt += dt
            if b.qt >= UNITS[k]['time']:
                if self.pop(b.team) < POP_MAX:
                    b.queue.pop(0)
                    b.qt = 0.0
                    u = Ent(k, b.team, b.x + random.uniform(-25, 25), b.y + b.r + 20)
                    self.ents.append(u)
                    if b.rally:
                        self.order_move(u, *b.rally)
                else:
                    b.qt = UNITS[k]['time']

    def separate(self):
        us = [e for e in self.ents if not e.b and not e.dead]
        for i, a in enumerate(us):
            for c in us[i + 1:]:
                dx, dy = c.x - a.x, c.y - a.y
                if abs(dx) > 30 or abs(dy) > 30:
                    continue
                d = math.hypot(dx, dy)
                m = a.r + c.r
                if 0 < d < m:
                    p = (m - d) / 2
                    dx, dy = dx / d * p, dy / d * p
                    a.x -= dx
                    a.y -= dy
                    c.x += dx
                    c.y += dy
                elif d == 0:
                    a.x += 0.5
            for ox, oy, orr in self.obst:
                dx, dy = a.x - ox, a.y - oy
                if abs(dx) > orr + 30 or abs(dy) > orr + 30:
                    continue
                d = math.hypot(dx, dy)
                m = a.r + orr
                if 0 < d < m - 1:
                    a.x += dx / d * (m - d)
                    a.y += dy / d * (m - d)
            a.x = max(a.r, min(MAP_W - a.r, a.x))
            a.y = max(a.r, min(MAP_H - a.r, a.y))

    def update(self, dt):
        self.time += dt
        self.msg_t = max(0, self.msg_t - dt)
        for e in self.ents:
            if not e.dead:
                (self.upd_building if e.b else self.upd_unit)(e, dt)
        self.separate()
        n = len(self.res)
        self.ents = [e for e in self.ents if not e.dead]
        self.res = [r for r in self.res if r.amount > 0]
        if len(self.res) != n:
            self.rebuild_obst()
        self.sel = [e for e in self.sel if not e.dead]
        for f in self.fx:
            f['life'] -= dt
            if f['t'] == 'p':
                f['x'] += f['vx'] * dt
                f['y'] += f['vy'] * dt
        self.fx = [f for f in self.fx if f['life'] > 0]
        self.ai(1, dt)
        if not any(e.kind == 'hq' and e.team == 1 for e in self.ents):
            self.over = 'VICTOIRE !'
        elif not any(e.kind == 'hq' and e.team == 0 for e in self.ents):
            self.over = 'DÉFAITE...'

    # ------------------------------------------------------------ IA
    @staticmethod
    def power(units):
        return sum(u.hp * u.d['dmg'] for u in units)

    def ai(self, T, dt):
        S = self.aist[T]
        S['t'] += dt
        if S['t'] < AI_THINK[self.diff]:
            return
        S['t'] = 0.0
        F = 1 - T
        st = self.stock[T]
        mine = [e for e in self.ents if e.team == T]
        hq = next((e for e in mine if e.kind == 'hq'), None)
        if not hq:
            return
        foes = [e for e in self.ents if e.team == F]
        workers = [e for e in mine if e.kind == 'worker']
        army = [e for e in mine if not e.b and e.kind != 'worker']
        blds = [e for e in mine if e.b]
        bars = [e for e in blds if e.kind == 'barracks']
        stables = [e for e in blds if e.kind == 'stable']
        cnt = lambda k: sum(1 for e in blds if e.kind == k)

        # --- économie
        target_w = 6 if not bars else (8 if len(army) < 8 else 10)
        if len(workers) < target_w and not hq.queue:
            self.queue(hq, 'worker')
        wood_w = [w for w in workers if w.mode == 'harvest' and w.ctype == 'wood']
        ore_w = [w for w in workers if w.mode == 'harvest' and w.ctype == 'ore']
        for w in workers:
            if w.mode == 'idle':
                kind = 'wood' if len(wood_w) <= 1.5 * len(ore_w) else 'ore'
                other = 'ore' if kind == 'wood' else 'wood'
                r = self.nearest_res(hq.x, hq.y, kind) or self.nearest_res(hq.x, hq.y, other)
                if r:
                    self.order_harvest(w, r)
                    (wood_w if r.kind == 'wood' else ore_w).append(w)
        if st['wood'] > st['ore'] + 150 and len(wood_w) > 1:
            r = self.nearest_res(hq.x, hq.y, 'ore')
            if r:
                self.order_harvest(wood_w[0], r)
        elif st['ore'] > st['wood'] + 150 and len(ore_w) > 1:
            r = self.nearest_res(hq.x, hq.y, 'wood')
            if r:
                self.order_harvest(ore_w[0], r)

        # --- construction (un chantier à la fois)
        if workers and all(b.built for b in blds):
            n = len(army)
            want = None
            if not bars:
                want = 'barracks'
            elif not stables and n >= 3:
                want = 'stable'
            elif cnt('tower') < 2 and n >= 5:
                want = 'tower'
            elif cnt('barracks') < 2 and n >= 8:
                want = 'barracks'
            elif len(stables) < 2 and n >= 12:
                want = 'stable'
            elif cnt('tower') < 4 and n >= 14:
                want = 'tower'
            elif cnt('depot') == 0 and st['wood'] >= 250:
                want = 'depot'
            if want:
                self.ai_build(T, hq, want, workers)

        # --- production adaptée à l'adversaire
        pk = [e.kind for e in foes if not e.b and e.kind != 'worker']
        cs, ca, ck = pk.count('soldier'), pk.count('archer'), pk.count('knight')
        if ck > 0 and ck >= max(ca, cs):
            counter = 'soldier'
        elif ca > 0 and ca >= cs:
            counter = 'knight'
        elif cs > 0:
            counter = 'archer'
        else:
            counter = random.choice(['soldier', 'archer', 'knight'])
        for b in bars + stables:
            if b.built and len(b.queue) < 2:
                opts = b.d['makes']
                k = counter if counter in opts and random.random() < 0.65 else random.choice(opts)
                self.queue(b, k)

        # --- défense
        threats = [e for e in foes if not e.b and any(dist(e.x, e.y, b.x, b.y) < 330 for b in blds)]
        if threats:
            for a in army:
                if dist(a.x, a.y, hq.x, hq.y) < 700 and (a.mode in ('idle', 'move', 'amove') or
                                                         (a.mode == 'attack' and a.target and a.target.b)):
                    t = min(threats, key=lambda e: dist(a.x, a.y, e.x, e.y))
                    self.order_attack(a, t)
            return

        # --- attaque par vagues
        wave = [a for a in army if a in S['wave']]
        if wave:
            S['wave'] = set(wave)
            if len(wave) < 0.35 * S['wave_size']:       # repli
                for a in wave:
                    self.order_move(a, hq.x + (self.bases[F][0] - hq.x) * 0.06, hq.y + (self.bases[F][1] - hq.y) * 0.06)
                S['wave'] = set()
                S['wave_n'] = min(22, S['wave_n'] + 3)
            else:
                tgt = self.ai_target(T, wave)
                if tgt:
                    for a in wave:
                        if a.mode == 'idle':
                            self.order_amove(a, tgt.x, tgt.y)
        else:
            ready = [a for a in army if a.mode == 'idle']
            if self.time >= AI_GRACE[self.diff] and len(ready) >= S['wave_n'] and (self.power(ready) >= 0.9 * self.power(self.mil(F)) or len(ready) >= 20):
                tgt = self.ai_target(T, ready)
                if tgt:
                    S['wave'], S['wave_size'] = set(ready), len(ready)
                    S['wave_n'] = min(22, S['wave_n'] + 2)
                    for a in ready:
                        self.order_amove(a, tgt.x, tgt.y)
            for a in ready:                              # regroupement près du QG
                if dist(a.x, a.y, hq.x, hq.y) > 350:
                    self.order_move(a, hq.x + (self.bases[F][0] - hq.x) * 0.06, hq.y + (self.bases[F][1] - hq.y) * 0.06)

    def ai_target(self, T, group):
        F = 1 - T
        cx = sum(a.x for a in group) / len(group)
        cy = sum(a.y for a in group) / len(group)
        bl = [e for e in self.ents if e.team == F and e.b]
        if not bl:
            return None
        return min(bl, key=lambda e: dist(e.x, e.y, cx, cy) - (150 if e.kind == 'hq' else 0))

    def ai_build(self, T, hq, kind, workers):
        if not self.affordable(T, BUILDINGS[kind]['cost']):
            return
        fx, fy = self.bases[1 - T]
        base_ang = math.atan2(fy - hq.y, fx - hq.x)
        for _ in range(25):
            if kind == 'tower':
                a, d = base_ang + random.uniform(-0.9, 0.9), random.uniform(190, 280)
            else:
                a, d = random.uniform(0, 6.283), random.uniform(130, 240)
            b = self.place(T, kind, hq.x + math.cos(a) * d, hq.y + math.sin(a) * d)
            if b:
                free_w = [w for w in workers if w.mode in ('idle', 'harvest')] or workers
                for w in sorted(free_w, key=lambda w: dist(w.x, w.y, b.x, b.y))[:2]:
                    self.order_build(w, b)
                return

    # ------------------------------------------------------------ entrées joueur
    def actions(self):
        own = [e for e in self.sel if e.team == 0]
        out = []
        if any(e.kind == 'worker' for e in own):
            for k in ('barracks', 'stable', 'depot', 'tower'):
                out.append(dict(kind=k, d=BUILDINGS[k], fn=lambda k=k: self.start_place(k)))
        kinds = []
        for e in own:
            if e.b and e.built:
                kinds += [k for k in e.d['makes'] if k not in kinds]
        for k in kinds:
            out.append(dict(kind=k, d=UNITS[k], fn=lambda k=k: self.produce(k)))
        if any(e.b and e.queue for e in own):
            out.append(dict(kind='cancel', d=dict(label='Annuler', cost=(0, 0)), fn=self.cancel_selected))
        for a in out:
            a['ok'] = self.affordable(0, a['d']['cost'])
        return out

    def pick(self, wx, wy):
        def dd(e):      # les sprites sont dessinés au-dessus de leurs pieds
            d = dist(e.x, e.y, wx, wy)
            return d if e.b else min(d, dist(e.x, e.y - e.r * 1.5, wx, wy))
        c = [e for e in self.ents if dd(e) <= e.r + 8]
        c.sort(key=lambda e: (e.b, dd(e)))
        return c[0] if c else None

    def select_rect(self, x0, y0, x1, y1):
        xa, xb, ya, yb = min(x0, x1), max(x0, x1), min(y0, y1), max(y0, y1)
        self.sel = [e for e in self.ents if e.team == 0 and not e.b and xa <= e.x <= xb and ya <= e.y <= yb]

    def select_kind(self, kind, x0, y0, x1, y1):
        self.sel = [e for e in self.ents if e.team == 0 and not e.b and e.kind == kind
                    and x0 <= e.x <= x1 and y0 <= e.y <= y1]

    def select_army(self):
        self.sel = self.mil(0)

    def select_idle_workers(self):
        self.sel = [e for e in self.ents if e.team == 0 and e.kind == 'worker' and e.mode == 'idle']
        if not self.sel:
            self.say('Aucun récolteur inactif')

    def stop_selected(self):
        for e in self.sel:
            if e.team == 0 and not e.b:
                self.stop(e)

    def command(self, wx, wy):
        own = [e for e in self.sel if e.team == 0]
        us = [e for e in own if not e.b]
        if not us:
            for b in own:
                if b.d['makes']:
                    b.rally = (wx, wy)
                    self.say('Point de ralliement défini')
            return
        tgt = next((e for e in self.ents if e.team == 1 and dist(e.x, e.y, wx, wy) <= e.r + 8), None)
        if tgt:
            self.amove = False
            for u in us:
                self.order_attack(u, tgt)
            return
        r = next((r for r in self.res if dist(r.x, r.y, wx, wy) <= r.r + 8), None)
        if r and not self.amove:
            for u in us:
                if u.kind == 'worker':
                    self.order_harvest(u, r)
                else:
                    self.order_move(u, r.x, r.y + 30)
            return
        fn = self.order_amove if self.amove else self.order_move
        self.amove = False
        n = len(us)
        cols = math.ceil(math.sqrt(n))
        rows = math.ceil(n / cols)
        for i, u in enumerate(us):
            ox = (i % cols - (cols - 1) / 2) * 28
            oy = (i // cols - (rows - 1) / 2) * 28
            fn(u, wx + ox, wy + oy)
