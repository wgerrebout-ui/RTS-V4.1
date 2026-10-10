"""
MINI RTS v4 - Android (Kivy) - vrais sprites (images dans assets_data.py)

Caméra : glisser | pincer = zoom | minimap en haut à droite
Toucher une unité = sélection (double-toucher = tous les mêmes à l'écran)
Toucher ailleurs = ordre (déplacer / attaquer / récolter)
Menu de gauche : Sélection (rectangle), Armée, Inactifs, Attaquer (attaque-déplacement), Stop, Pause, Niveau
Récolteur sélectionné -> bâtiment : glisser l'aperçu puis "Poser ici" (les récolteurs vont construire)
"""
import base64
import io
import math
import random

from kivy.app import App
from kivy.clock import Clock
from kivy.core.image import Image as CoreImage
from kivy.graphics import (BorderImage, Color, Line, PopMatrix, PushMatrix, Rectangle, Rotate)
from kivy.metrics import dp
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.widget import Widget

from assets_data import DATA
from game import (BUILDINGS, DIFF_NAMES, MAP_H, MAP_W, POP_MAX, UNITS, Game)

VIEW_WORLD_H = 640
TEAM = {0: (0.25, 0.55, 1.0), 1: (0.93, 0.27, 0.25)}

# ------------------------------------------------------------------ textures
_T = {}


def tex(name):
    t = _T.get(name)
    if t is None:
        t = CoreImage(io.BytesIO(base64.b64decode(DATA[name])), ext='png').texture
        t.mag_filter = 'linear'
        t.min_filter = 'linear'
        if name == 'grass':
            t.wrap = 'repeat'
        _T[name] = t
    return t


# taille du canevas, ancre x, pied (px depuis le bas), hauteur visible (px)
UNIT_META = {
    'worker': dict(w=112, h=112, ax=54, foot=10, top=76),
    'soldier': dict(w=112, h=112, ax=54, foot=10, top=92),
    'archer': dict(w=112, h=112, ax=54, foot=10, top=88),
    'knight': dict(w=160, h=140, ax=75, foot=12, top=122),
}
UNIT_WS = 0.55                    # px monde par px de sprite
BLD_META = {
    'hq': dict(w=224, h=210, base=196, s=0.54),
    'barracks': dict(w=200, h=170, base=156, s=0.50),
    'stable': dict(w=200, h=170, base=156, s=0.50),
    'depot': dict(w=160, h=140, base=126, s=0.48),
    'tower': dict(w=112, h=190, base=178, s=0.60),
}
GRASS_WORLD = 230.0

ROLE = {
    'worker': 'Récolte le bois et le minerai, construit',
    'soldier': 'Corps à corps, solide. Bat le cavalier',
    'archer': 'Tire de loin, fragile. Bat le soldat',
    'knight': 'Cavalier rapide. Bat l\'archer',
    'hq': 'Votre base : produit des récolteurs',
    'barracks': 'Produit soldats et archers',
    'stable': 'Produit des cavaliers',
    'depot': 'Dépôt : raccourcit les trajets de récolte',
    'tower': 'Tire sur les ennemis proches',
}


# ------------------------------------------------------------------ petits widgets
def attach_bg(w, name, border=24):
    with w.canvas.before:
        Color(1, 1, 1, 1)
        w._bg = BorderImage(texture=tex(name), border=(border,) * 4, pos=w.pos, size=w.size)
    w._bgname = name
    w.bind(pos=lambda *_: setattr(w._bg, 'pos', w.pos), size=lambda *_: setattr(w._bg, 'size', w.size))


def set_bg(w, name):
    if w._bgname != name:
        w._bgname = name
        w._bg.texture = tex(name)


class Pic(Widget):
    """Affiche une image en conservant ses proportions."""

    def __init__(self, name=None, pad=0, **kw):
        super().__init__(**kw)
        self.name = name
        self.pad = pad
        self.bind(pos=self.rd, size=self.rd)
        self.rd()

    def set(self, name):
        if name != self.name:
            self.name = name
            self.rd()

    def rd(self, *a):
        self.canvas.clear()
        if not self.name or self.width < 2:
            return
        t = tex(self.name)
        w, h = t.size
        k = min((self.width - 2 * self.pad) / w, (self.height - 2 * self.pad) / h)
        dw, dh = w * k, h * k
        with self.canvas:
            Color(1, 1, 1, 1)
            Rectangle(texture=t, pos=(self.center_x - dw / 2, self.center_y - dh / 2), size=(dw, dh))


class ToolBtn(ButtonBehavior, FloatLayout):
    def __init__(self, icon, caption, **kw):
        super().__init__(**kw)
        attach_bg(self, 'ui_btn')
        self.pic = Pic(icon, pad=dp(3), size_hint=(1, .66), pos_hint={'x': 0, 'top': .97})
        self.lab = Label(text=caption, font_size=dp(9.5), size_hint=(1, .3), pos_hint={'x': 0, 'y': .02},
                         color=(1, 1, 1, 1), bold=True)
        self.add_widget(self.pic)
        self.add_widget(self.lab)
        self.on = False
        self.bind(state=lambda *_: self.restyle())

    def restyle(self):
        set_bg(self, 'ui_btn_on' if self.on else ('ui_btn_down' if self.state == 'down' else 'ui_btn'))

    def set_on(self, on):
        if on != self.on:
            self.on = on
            self.restyle()


class Card(ButtonBehavior, BoxLayout):
    """Carte d'action : icône de l'unité / du bâtiment, nom, coût."""

    def __init__(self, kind, label, cost, icon, **kw):
        super().__init__(orientation='vertical', padding=(dp(4), dp(3)), spacing=dp(1), **kw)
        attach_bg(self, 'ui_card')
        self.ok = True
        self.pic = Pic(icon, pad=dp(1), size_hint=(1, .52))
        self.name = Label(text=label, font_size=dp(11), bold=True, size_hint=(1, .2), color=(1, 1, 1, 1))
        row = BoxLayout(size_hint=(1, .28), spacing=dp(1))
        self.costs = []
        for ic, v in (('i_wood', cost[0]), ('i_ore', cost[1])):
            if v:
                row.add_widget(Pic(ic, size_hint=(None, 1), width=dp(15)))
                lb = Label(text=str(v), font_size=dp(11), size_hint=(.5, 1), color=(1, 1, 1, 1), bold=True)
                row.add_widget(lb)
                self.costs.append(lb)
        self.add_widget(self.pic)
        self.add_widget(self.name)
        self.add_widget(row)
        self.bind(state=lambda *_: self.restyle())

    def restyle(self):
        if not self.ok:
            set_bg(self, 'ui_btn_bad')
        else:
            set_bg(self, 'ui_btn_down' if self.state == 'down' else 'ui_card')

    def set_ok(self, ok):
        if ok != self.ok:
            self.ok = ok
            for lb in self.costs:
                lb.color = (1, 1, 1, 1) if ok else (1, .55, .55, 1)
            self.restyle()


# ------------------------------------------------------------------ vue du jeu
class GameView(Widget):
    def __init__(self, g, **kw):
        super().__init__(**kw)
        self.g = g
        self.rect_mode = False
        self.zoom = 1.0
        self.touches = {}
        self.pinch0 = None
        self.pinching = False
        self.start = self.cur = None
        self.moved = False
        self.dbl = False
        self.mm_drag = False
        self.ghost = None
        self.make_decor()
        Clock.schedule_interval(self.tick, 1 / 30)

    def make_decor(self):
        rnd = random.Random(7)
        names = ['tuft_0', 'tuft_1', 'tuft_2', 'flower_0', 'flower_1', 'flower_2', 'flower_3']
        self.decor = []
        for _ in range(420):
            n = rnd.choice(names) if rnd.random() < .6 else rnd.choice(names[:3])
            self.decor.append((rnd.uniform(30, MAP_W - 30), rnd.uniform(30, MAP_H - 30), n))

    # ---- conversions
    @property
    def sc(self):
        return max(1.0, self.height) / VIEW_WORLD_H * self.zoom

    def w2s(self, x, y):
        return (x - self.g.cam[0]) * self.sc, self.height - (y - self.g.cam[1]) * self.sc

    def s2w(self, sx, sy):
        return sx / self.sc + self.g.cam[0], (self.height - sy) / self.sc + self.g.cam[1]

    def view_world(self):
        return self.width / self.sc, self.height / self.sc

    def clamp_cam(self):
        vw, vh = self.view_world()
        c = self.g.cam
        c[0] = max(0, min(max(0, MAP_W - vw), c[0]))
        c[1] = max(0, min(max(0, MAP_H - vh), c[1]))

    def mm_rect(self):
        w = self.width * 0.17
        h = w * MAP_H / MAP_W
        return self.width - w - dp(8), self.height - h - dp(44), w, h

    def tick(self, dt):
        g = self.g
        if not g.paused and not g.over:
            g.update(min(dt, 0.05))
        self.clamp_cam()
        if g.placing and self.ghost is None:
            vw, vh = self.view_world()
            self.ghost = (g.cam[0] + vw / 2, g.cam[1] + vh / 2)
        if not g.placing:
            self.ghost = None
        self.draw()

    # ---- primitives
    def blit(self, name, x, y, w, h, flip=False, col=(1, 1, 1, 1)):
        Color(*col)
        if flip:
            Rectangle(texture=tex(name), pos=(x, y), size=(w, h), tex_coords=(1, 0, 0, 0, 0, 1, 1, 1))
        else:
            Rectangle(texture=tex(name), pos=(x, y), size=(w, h))

    def rect(self, x, y, w, h):
        Rectangle(pos=(x, y), size=(w, h))

    # ---- dessin
    def draw(self):
        g, sc = self.g, self.sc
        self.canvas.clear()
        with self.canvas:
            Color(0.06, 0.09, 0.07)
            self.rect(0, 0, self.width, self.height)
            self.draw_terrain()
            items = []
            for r in g.res:
                items.append((r.y, 0, r))
            for e in g.ents:
                items.append((e.y + (e.r * .45 if e.b else 0), 1, e))
            items.sort(key=lambda t: t[0])
            for rk in g.rocks:
                items.append((rk[1], 2, rk))
            items.sort(key=lambda t: t[0])
            vis = dp(150)
            for _, kind, o in items:
                if kind == 2:
                    sx, sy = self.w2s(o[0], o[1])
                else:
                    sx, sy = self.w2s(o.x, o.y)
                if sx < -vis or sx > self.width + vis or sy < -vis or sy > self.height + vis:
                    continue
                if kind == 0:
                    self.draw_resource(o, sx, sy, sc)
                elif kind == 2:
                    self.draw_rock(o, sx, sy, sc)
                elif o.b:
                    self.draw_building(o, sx, sy, sc)
                else:
                    self.draw_unit(o, sx, sy, sc)
            self.draw_fx(sc)
            if g.placing and self.ghost:
                self.draw_ghost(sc)
            if self.rect_mode and self.start and self.cur and self.moved:
                x0, y0 = self.start
                x1, y1 = self.cur
                Color(0.4, 1, 0.4, 0.15)
                self.rect(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))
                Color(0.5, 1, 0.5)
                Line(rectangle=(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0)), width=1.6)
            self.draw_minimap()

    def draw_terrain(self):
        g, sc = self.g, self.sc
        sx0, sy0 = self.w2s(0, MAP_H)
        mw, mh = MAP_W * sc, MAP_H * sc
        x0, y0 = max(0, sx0), max(0, sy0)
        x1, y1 = min(self.width, sx0 + mw), min(self.height, sy0 + mh)
        if x1 <= x0 or y1 <= y0:
            return
        wx0, wy1 = self.s2w(x0, y0)
        wx1, wy0 = self.s2w(x1, y1)
        T = GRASS_WORLD
        u0, u1, vb, vt = wx0 / T, wx1 / T, -wy1 / T, -wy0 / T
        Color(1, 1, 1, 1)
        Rectangle(texture=tex('grass'), pos=(x0, y0), size=(x1 - x0, y1 - y0), tex_coords=(u0, vb, u1, vb, u1, vt, u0, vt))
        for bx, by in g.bases.values():                    # terre autour des bases
            cx, cy = self.w2s(bx, by)
            R = 330 * sc
            self.blit('dirt', cx - R, cy - R, 2 * R, 2 * R)
        for x, y, n in self.decor:                          # herbes et fleurs
            sx, sy = self.w2s(x, y)
            if -40 < sx < self.width + 40 and -40 < sy < self.height + 40:
                t = tex(n)
                k = .55 * sc
                self.blit(n, sx - t.width * k / 2, sy - 2 * k, t.width * k, t.height * k)
        Color(0.05, 0.08, 0.05, 1)
        Line(rectangle=(sx0, sy0, mw, mh), width=3)

    def draw_rock(self, rk, sx, sy, sc):
        x, y, r = rk
        w = r * 2.7 * sc
        h = w * .8
        self.blit('rock_%d' % (int(x * 3 + y) % 3), sx - w / 2, sy - h * .22 - r * .5 * sc, w, h)

    def draw_resource(self, o, sx, sy, sc):
        k = 0.65 + 0.35 * min(1, o.amount / o.max)
        if o.kind == 'wood':
            n = 'tree_%d' % (int(o.x * 7 + o.y * 13) % 3)
            w, h = 96 * .46 * sc * k, 130 * .46 * sc * k
            self.blit(n, sx - w / 2, sy - h * .07 - 4 * sc, w, h)
        else:
            n = 'ore_%d' % (int(o.x * 5 + o.y * 11) % 2)
            w, h = 92 * .5 * sc * k, 80 * .5 * sc * k
            self.blit(n, sx - w / 2, sy - h * .12 - 4 * sc, w, h)

    def hp_bar(self, e, cx, y, w):
        if e not in self.g.sel and e.hp >= e.maxhp:
            return
        f = max(0, e.hp) / e.maxhp
        Color(0, 0, 0, 0.8)
        self.rect(cx - w / 2 - 2, y - 2, w + 4, 9)
        Color(0.3, 0.06, 0.06)
        self.rect(cx - w / 2, y, w, 5)
        Color(1 - f, 0.25 + 0.7 * f, 0.15)
        self.rect(cx - w / 2, y, w * f, 5)
        Color(1, 1, 1, 0.3)
        self.rect(cx - w / 2, y + 3, w * f, 2)

    def draw_unit(self, e, sx, sy, sc):
        g = self.g
        m = UNIT_META[e.kind]
        sf = UNIT_WS * sc
        f = 1 if math.cos(e.ang) >= 0 else -1
        ph = hash(id(e)) % 10
        t = g.time
        if e.flash > 0:
            fr = 'atk'
        elif e.working:
            fr = 'atk' if int((t + ph * .1) * 4) % 2 == 0 else 'idle'
        elif e.moving:
            fr = 'walk1' if int((t + ph * .05) * 5.5) % 2 == 0 else 'walk2'
        else:
            fr = 'idle'
        rw = e.r * 3.0 * sc
        self.blit('ring_t%d' % e.team, sx - rw / 2, sy - rw / 4, rw, rw / 2)
        if e in g.sel:
            sw = e.r * 3.7 * sc
            self.blit('ring_sel' if e.team == 0 else 'ring_sel_e', sx - sw / 2, sy - sw / 4, sw, sw / 2)
        w, h = m['w'] * sf, m['h'] * sf
        lunge = (e.flash / .15) * 5 * sf * f if (e.flash > 0 and e.d['rng'] < 60) else 0
        x = sx - (m['ax'] if f > 0 else m['w'] - m['ax']) * sf + lunge
        y = sy - m['foot'] * sf
        self.blit('u_%s_%d_%s' % (e.kind, e.team, fr), x, y, w, h, flip=(f < 0))
        if e.kind == 'worker' and e.carry:
            cn = 'carry_ore' if e.ctype == 'ore' else 'carry_wood'
            cs = 30 * sf
            self.blit(cn, sx - f * 20 * sf - cs / 2, sy + 22 * sf, cs, cs * (.7 if cn == 'carry_wood' else 1))
        self.hp_bar(e, sx, sy + m['top'] * sf + 6, max(34 * sf, 26))

    def draw_building(self, e, sx, sy, sc):
        m = BLD_META[e.kind]
        s = m['s'] * sc
        w, h = m['w'] * s, m['h'] * s
        base_y = sy - e.r * .45 * sc
        x = sx - w / 2
        y = base_y - (m['h'] - m['base']) * s
        if e in self.g.sel:
            rw = e.r * 3.3 * sc
            self.blit('ring_sel' if e.team == 0 else 'ring_sel_e', sx - rw / 2, base_y - rw / 4, rw, rw / 2)
        if e.built:
            self.blit('b_%s_%d' % (e.kind, e.team), x, y, w, h)
        else:
            prog = min(1, e.bt / e.d['time'])
            self.blit('b_%s_%d' % (e.kind, e.team), x, y, w, h, col=(1, 1, 1, .3 + .7 * prog))
            sw, sh = 200 * s, 170 * s
            self.blit('scaffold', sx - sw / 2, base_y - 14 * s, sw, sh, col=(1, 1, 1, .95 - .5 * prog))
            Color(0, 0, 0, 0.8)
            self.rect(sx - 44 * sc, y + h + 6, 88 * sc, 10)
            Color(1, 0.8, 0.2)
            self.rect(sx - 42 * sc, y + h + 8, 84 * sc * prog, 6)
        if e.built and e.queue:
            prog = e.qt / UNITS[e.queue[0]]['time']
            ic = 'ic_%s_%d' % (e.queue[0], e.team)
            self.blit(ic, sx - 40 * sc, base_y - 30 * sc, 24 * sc, 24 * sc)
            Color(0, 0, 0, 0.8)
            self.rect(sx - 12 * sc, base_y - 22 * sc, 52 * sc, 10)
            Color(0.95, 0.95, 0.95)
            self.rect(sx - 10 * sc, base_y - 20 * sc, 48 * sc * prog, 6)
            if len(e.queue) > 1:
                Color(1, 1, 1, .9)
                for i in range(len(e.queue) - 1):
                    self.rect(sx + 44 * sc + i * 8 * sc, base_y - 22 * sc, 5 * sc, 5 * sc)
        if e in self.g.sel:
            if 'rng' in e.d:
                Color(1, 1, 1, 0.4)
                Line(circle=(sx, sy, e.d['rng'] * sc), width=1.4)
            if e.rally and e.team == 0:
                rx, ry = self.w2s(*e.rally)
                Color(0.4, 1, 0.4)
                Line(points=[sx, sy, rx, ry], width=1.2)
                self.blit('ring_sel', rx - 20, ry - 10, 40, 20)
        self.hp_bar(e, sx, y + h * (.99 if e.kind != 'tower' else .96) + 4, max(70 * sc * s / .5 * .5, 44))

    def draw_ghost(self, sc):
        g = self.g
        k = g.placing
        m = BLD_META[k]
        d = BUILDINGS[k]
        s = m['s'] * sc
        gx, gy = self.w2s(*self.ghost)
        ok = g.can_place(0, k, *self.ghost)
        base_y = gy - d['r'] * .45 * sc
        col = (0.5, 1, 0.5, .8) if ok else (1, 0.45, 0.45, .8)
        rw = d['r'] * 2.4 * sc
        Color(*(col[:3] + (.25,)))
        self.blit('ring_sel' if ok else 'ring_sel_e', gx - rw / 2 * 1.3, base_y - rw / 4 * 1.3, rw * 1.3, rw / 2 * 1.3)
        self.blit('b_%s_0' % k, gx - m['w'] * s / 2, base_y - (m['h'] - m['base']) * s, m['w'] * s, m['h'] * s, col=col)
        if 'rng' in d:
            Color(1, 1, 1, 0.35)
            Line(circle=(gx, gy, d['rng'] * sc), width=1.4)

    def draw_fx(self, sc):
        for f in self.g.fx:
            k = f['life'] / f['max']
            if f['t'] == 'p':
                sx, sy = self.w2s(f['x'], f['y'])
                sz = f['size'] * sc * (3.2 + 4 * (1 - k))
                c = f['col']
                self.blit('puff', sx - sz / 2, sy - sz / 2, sz, sz, col=(c[0], c[1], c[2], k * .9))
            else:
                p = 1 - k
                ax, ay = f['x'] + (f['x1'] - f['x']) * p, f['y'] + (f['y1'] - f['y']) * p
                sx, sy = self.w2s(ax, ay)
                s0x, s0y = self.w2s(f['x'], f['y'])
                s1x, s1y = self.w2s(f['x1'], f['y1'])
                ang = math.degrees(math.atan2(s1y - s0y, s1x - s0x))
                PushMatrix()
                Rotate(angle=ang, origin=(sx, sy + 22 * sc))
                self.blit('arrow', sx - 18 * sc, sy + 22 * sc - 4 * sc, 36 * sc, 8 * sc)
                PopMatrix()

    def draw_minimap(self):
        g, sc = self.g, self.sc
        mx, my, mw, mh = self.mm_rect()
        Color(0, 0, 0, 0.7)
        self.rect(mx - 4, my - 4, mw + 8, mh + 8)
        Color(0.25, 0.45, 0.25)
        self.rect(mx, my, mw, mh)
        for bx, by in g.bases.values():
            Color(0.55, 0.43, 0.3, .8)
            self.rect(mx + (bx - 150) / MAP_W * mw, my + mh - (by + 150) / MAP_H * mh, 300 / MAP_W * mw, 300 / MAP_H * mh)
        for x, y, r in g.rocks:
            Color(0.6, 0.6, 0.65)
            self.rect(mx + x / MAP_W * mw, my + mh - y / MAP_H * mh, 2.5, 2.5)
        for r in g.res:
            Color(0.1, 0.45, 0.2) if r.kind == 'wood' else Color(1, 0.85, 0.2)
            self.rect(mx + r.x / MAP_W * mw, my + mh - r.y / MAP_H * mh, 2.5, 2.5)
        for e in g.ents:
            Color(*TEAM[e.team])
            s = 6 if e.b else 3.2
            self.rect(mx + e.x / MAP_W * mw - s / 2, my + mh - e.y / MAP_H * mh - s / 2, s, s)
        vw, vh = self.view_world()
        Color(1, 1, 1)
        Line(rectangle=(mx + g.cam[0] / MAP_W * mw, my + mh - (g.cam[1] + vh) / MAP_H * mh,
                        vw / MAP_W * mw, vh / MAP_H * mh), width=1.3)

    # ---- tactile
    def in_mm(self, x, y):
        mx, my, mw, mh = self.mm_rect()
        return mx <= x <= mx + mw and my <= y <= my + mh

    def mm_jump(self, x, y):
        mx, my, mw, mh = self.mm_rect()
        vw, vh = self.view_world()
        self.g.cam[0] = (x - mx) / mw * MAP_W - vw / 2
        self.g.cam[1] = (my + mh - y) / mh * MAP_H - vh / 2

    def on_touch_down(self, t):
        if not self.collide_point(*t.pos):
            return False
        self.touches[t.uid] = (t.x, t.y)
        if len(self.touches) >= 2:
            pts = list(self.touches.values())[:2]
            self.pinch0 = (math.hypot(pts[0][0] - pts[1][0], pts[0][1] - pts[1][1]) or 1, self.zoom)
            self.pinching = True
            self.start = None
            return True
        if self.in_mm(t.x, t.y):
            self.mm_drag = True
            self.mm_jump(t.x, t.y)
            return True
        self.start = self.cur = (t.x, t.y)
        self.moved = False
        self.dbl = bool(getattr(t, 'is_double_tap', False))
        if self.g.placing:
            self.ghost = self.s2w(t.x, t.y)
        return True

    def on_touch_move(self, t):
        if t.uid not in self.touches:
            return False
        self.touches[t.uid] = (t.x, t.y)
        if self.pinching:
            if len(self.touches) >= 2 and self.pinch0:
                pts = list(self.touches.values())[:2]
                d = math.hypot(pts[0][0] - pts[1][0], pts[0][1] - pts[1][1]) or 1
                self.zoom = max(0.6, min(1.8, self.pinch0[1] * d / self.pinch0[0]))
            return True
        if self.mm_drag:
            self.mm_jump(t.x, t.y)
            return True
        if not self.start:
            return False
        if math.hypot(t.x - self.start[0], t.y - self.start[1]) > dp(12):
            self.moved = True
        self.cur = (t.x, t.y)
        if self.g.placing:
            self.ghost = self.s2w(t.x, t.y)
        elif not self.rect_mode and self.moved:
            self.g.cam[0] -= t.dx / self.sc
            self.g.cam[1] += t.dy / self.sc
        return True

    def on_touch_up(self, t):
        if t.uid not in self.touches:
            return False
        del self.touches[t.uid]
        if self.pinching:
            if not self.touches:
                self.pinching = False
            return True
        self.mm_drag = False
        if not self.start:
            return False
        g = self.g
        start, self.start = self.start, None
        if g.placing:
            return True
        if self.rect_mode and self.moved:
            x0, y0 = self.s2w(*start)
            x1, y1 = self.s2w(t.x, t.y)
            g.select_rect(x0, y0, x1, y1)
            self.rect_mode = False
            return True
        if self.moved:
            return True
        wx, wy = self.s2w(t.x, t.y)
        hit = g.pick(wx, wy)
        own = [e for e in g.sel if e.team == 0]
        if hit and hit.team == 0:
            if self.dbl and not hit.b:
                vw, vh = self.view_world()
                g.select_kind(hit.kind, g.cam[0], g.cam[1], g.cam[0] + vw, g.cam[1] + vh)
            else:
                g.sel = [hit]
        elif own:
            g.command(wx, wy)
        else:
            g.sel = [hit] if hit else []
        return True


# ------------------------------------------------------------------ application
class RTSApp(App):
    def build(self):
        self.g = Game()
        self.g.cam = [0, MAP_H - 640]
        root = FloatLayout()
        self.view = GameView(self.g, size_hint=(1, 1))
        root.add_widget(self.view)

        # --- HUD ressources
        hud = BoxLayout(size_hint=(None, None), size=(dp(330), dp(36)), pos_hint={'x': 0.004, 'top': 0.996},
                        padding=(dp(8), dp(3)), spacing=dp(3))
        attach_bg(hud, 'ui_panel', 16)
        self.hud = {}
        for key, icon in (('wood', 'i_wood'), ('ore', 'i_ore'), ('pop', 'i_pop')):
            hud.add_widget(Pic(icon, size_hint=(None, 1), width=dp(26)))
            lb = Label(text='0', font_size=dp(16), bold=True, size_hint=(1, 1), halign='left', valign='middle',
                       color=(1, 1, 1, 1))
            lb.bind(size=lambda w, s: setattr(w, 'text_size', s))
            hud.add_widget(lb)
            self.hud[key] = lb
        root.add_widget(hud)
        self.msg = Label(text='', font_size=dp(14), bold=True, size_hint=(None, None), size=(dp(380), dp(30)),
                         pos_hint={'center_x': .5, 'top': .93}, color=(1, .92, .6, 1))
        attach_bg(self.msg, 'ui_panel', 16)
        self.msg.opacity = 0
        root.add_widget(self.msg)

        # --- outils (colonne de gauche)
        grid = GridLayout(cols=2, spacing=dp(4), size_hint=(None, None), size=(dp(108), dp(4 * 56 - 4)),
                          pos_hint={'x': 0.004, 'center_y': 0.58})
        self.tb = {}
        for name, cap, icon, fn in (
                ('rect', 'Sélection', 'i_rect', self.toggle_rect),
                ('army', 'Armée', 'i_army', lambda: self.g.select_army()),
                ('idle', 'Inactifs', 'i_idle', lambda: self.g.select_idle_workers()),
                ('amove', 'Attaquer', 'i_amove', self.toggle_amove),
                ('stop', 'Stop', 'i_stop', lambda: self.g.stop_selected()),
                ('pause', 'Pause', 'i_pause', self.toggle_pause),
                ('diff', 'Niveau', 'i_diff', self.cycle_diff)):
            b = ToolBtn(icon, cap, size_hint=(None, None), size=(dp(52), dp(52)))
            b.bind(on_release=lambda *_, f=fn: f())
            self.tb[name] = b
            grid.add_widget(b)
        root.add_widget(grid)

        # --- barre du bas
        self.bar = BoxLayout(size_hint=(1, None), height=dp(92), spacing=dp(5), padding=(dp(6), dp(5)))
        attach_bg(self.bar, 'ui_panel', 20)
        root.add_widget(self.bar)
        self.portrait = Pic(None, pad=dp(2), size_hint=(None, 1), width=dp(78))
        self.info = Label(size_hint=(None, 1), width=dp(215), font_size=dp(12), halign='left', valign='middle',
                          markup=True, color=(1, 1, 1, 1))
        self.info.bind(size=lambda w, s: setattr(w, 'text_size', s))
        self.sig = None
        self.cards = []
        Clock.schedule_interval(self.refresh, 1 / 8)
        return root

    def refresh(self, dt):
        g, v = self.g, self.view
        st = g.stock[0]
        self.hud['wood'].text = str(st['wood'])
        self.hud['ore'].text = str(st['ore'])
        self.hud['pop'].text = f'{g.pop(0)}/{POP_MAX}'
        self.msg.text = g.msg
        self.msg.opacity = 1 if g.msg_t > 0 else 0
        acts = g.actions()
        sig = (tuple(a['kind'] for a in acts), g.placing, g.over)
        sel = g.sel
        pk = None
        if len(sel) == 1:
            e = sel[0]
            pk = (e.kind, e.team)
            line = f"[b][size=15sp]{e.d['label']}[/size][/b]{' [color=ff8080](ennemi)[/color]' if e.team else ''}\n"
            line += f"[color=cfd8ec]{ROLE[e.kind]}[/color]\n"
            line += f"PV {int(e.hp)}/{e.maxhp}"
            if not e.b:
                line += f"   Dégâts {e.d['dmg']}   Portée {e.d['rng']}"
            if e.b and not e.built:
                line += f"\nChantier : {int(100 * e.bt / e.d['time'])} %"
            elif e.b and e.queue:
                line += '\nProduction : ' + ', '.join(UNITS[k]['label'] for k in e.queue)
            if e.kind == 'worker' and e.carry:
                line += f"\nPorte {e.carry} {'minerai' if e.ctype == 'ore' else 'bois'}"
        elif sel:
            ks = [x.kind for x in sel if not x.b]
            if ks:
                top = max(set(ks), key=ks.count)
                pk = (top, 0)
                line = f'[b][size=15sp]{len(sel)} unités[/size][/b]\n' + ', '.join(
                    f'{ks.count(k)} {UNITS[k]["label"]}' for k in dict.fromkeys(ks))
            else:
                line = f'{len(sel)} sélectionnés'
        else:
            line = ('[b]Rien de sélectionné[/b]\nGlisser : caméra   Pincer : zoom\n'
                    'Toucher une unité pour la sélectionner')
        self.info.text = line
        self.portrait.set('ic_%s_%d' % pk if pk else None)
        for name in ('rect', 'amove'):
            self.tb[name].set_on(v.rect_mode if name == 'rect' else g.amove)
        self.tb['pause'].lab.text = 'Reprise' if g.paused else 'Pause'
        self.tb['pause'].pic.set('i_play' if g.paused else 'i_pause')
        self.tb['diff'].lab.text = DIFF_NAMES[g.diff]
        if sig != self.sig:
            self.sig = sig
            self.bar.clear_widgets()
            self.cards = []
            if g.over:
                c = Card('over', g.over + '  Rejouer', (0, 0), 'i_ok', size_hint=(1, 1))
                c.bind(on_release=lambda *_: self.new_game())
                self.bar.add_widget(c)
            else:
                self.bar.add_widget(self.portrait)
                self.bar.add_widget(self.info)
                self.bar.add_widget(Widget())
                if g.placing:
                    for lab, ic, fn in (('Poser ici', 'i_ok', self.confirm_place),
                                        ('Annuler', 'i_cancel', lambda: setattr(g, 'placing', None))):
                        c = Card(lab, lab, (0, 0), ic, size_hint=(None, 1), width=dp(96))
                        c.bind(on_release=lambda *_, f=fn: f())
                        self.bar.add_widget(c)
                else:
                    for a in acts:
                        icon = 'i_cancel' if a['kind'] == 'cancel' else 'ic_%s_0' % a['kind']
                        c = Card(a['kind'], a['d']['label'], a['d']['cost'], icon, size_hint=(None, 1), width=dp(90))
                        c.bind(on_release=lambda *_, f=a['fn']: f())
                        self.bar.add_widget(c)
                        self.cards.append(c)
        if not g.over and not g.placing:
            for c, a in zip(self.cards, acts):
                c.set_ok(a['ok'])

    def toggle_rect(self):
        self.view.rect_mode = not self.view.rect_mode
        if self.view.rect_mode:
            self.g.say('Glissez sur l\'écran pour entourer vos unités')

    def toggle_amove(self):
        self.g.amove = not self.g.amove
        if self.g.amove:
            self.g.say("Attaquer en route : touchez la destination")

    def toggle_pause(self):
        self.g.paused = not self.g.paused

    def cycle_diff(self):
        self.g.diff = (self.g.diff + 1) % 3
        self.g.say('Niveau : ' + DIFF_NAMES[self.g.diff] + ' (à la prochaine partie)')

    def confirm_place(self):
        g, v = self.g, self.view
        if v.ghost and g.build_with_selected(g.placing, *v.ghost):
            g.placing = None
        else:
            g.say('Emplacement invalide (près de vos bâtiments, sans obstacle)')

    def new_game(self):
        self.g.reset()
        self.g.cam = [0, MAP_H - 640]
        self.sig = None


if __name__ == '__main__':
    RTSApp().run()
