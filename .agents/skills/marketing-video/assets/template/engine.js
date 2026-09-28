const B = window.BRAND;
const OPT = window.OPTIONS;
const tl = gsap.timeline({ paused: true });
const FADE = OPT.transitions === 'fade' ? 0.4 : 0;
const CARD = 1.35;
const $ = (tag, cls, parent, html) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html != null) e.innerHTML = html;
  parent.appendChild(e);
  return e;
};
const pad2 = (n) => String(n).padStart(2, '0');
const logo = (key, h) => `<img class="logo-img" src="../${B.logos[key]}" style="height:${h}px" alt="">`;
const lockup = (h) => (B.logos.b ? `${logo('a', h)}<span class="x">×</span>${logo('b', h)}` : logo('a', h));

function words(el) {
  const walk = (n) => {
    for (const c of [...n.childNodes]) {
      if (c.nodeType === 1 && c.tagName !== 'BR') walk(c);
      if (c.nodeType !== 3) continue;
      const frag = document.createDocumentFragment();
      for (const w of c.textContent.split(/(\s+)/).filter(Boolean)) {
        if (/^\s+$/.test(w)) frag.appendChild(document.createTextNode(w));
        else $('span', 'w', frag, `<span class="wi">${w}</span>`);
      }
      c.replaceWith(frag);
    }
  };
  walk(el);
  return el.querySelectorAll('.wi');
}
const reveal = (el, at, stagger = 0.07) => tl.from(words(el), { yPercent: 115, duration: 0.9, ease: 'expo.out', stagger }, at);
const popIn = (targets, at, opts = {}) =>
  tl.from(
    targets,
    {
      opacity: 0,
      y: 70,
      duration: 0.9,
      ease: 'expo.out',
      stagger: 0.12,
      ...opts,
    },
    at,
  );
const draw = (path, at, duration) => {
  const length = path.getTotalLength();
  gsap.set(path, { strokeDasharray: length, strokeDashoffset: length });
  tl.to(path, { strokeDashoffset: 0, duration, ease: 'power2.inOut' }, at);
};
const svgEl = (tag, attrs, parent) => {
  const e = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  parent.appendChild(e);
  return e;
};

function sceneRoot(s, i) {
  const root = $('div', 'scene', document.getElementById('scenes'));
  tl.set(root, { visibility: 'visible' }, s.start);
  tl.set(root, { visibility: 'hidden' }, s.start + s.dur + FADE);
  if (FADE && i > 0) tl.fromTo(root, { opacity: 0 }, { opacity: 1, duration: FADE, ease: 'power1.inOut' }, s.start);
  return root;
}

function chapter(s, root) {
  const card = $(
    'div',
    'chapcard',
    root,
    `<div class="num">${pad2(s.num)}</div><div class="kick">${pad2(s.num)}${s.who ? ` — ${s.who}` : ''}</div><div class="big">${s.label}</div>`,
  );
  tl.from(card.querySelector('.kick'), { yPercent: 120, opacity: 0, duration: 0.6, ease: 'expo.out' }, s.start + 0.05);
  tl.from(card.querySelector('.num'), { yPercent: 30, opacity: 0, duration: 1.0, ease: 'expo.out' }, s.start);
  reveal(card.querySelector('.big'), s.start + 0.12, 0.06);
  tl.to(card, { yPercent: -100, duration: 0.75, ease: 'expo.inOut' }, s.start + CARD - 0.35);
}

function slab(root, box, n, caption, speed, at, out) {
  const fast = speed >= 3 ? `<span class="fast">${speed}×</span>` : '';
  const e = $('div', 'slab', root, `<span class="n">${n}</span><span class="t">${caption}</span>${fast}`);
  gsap.set(e, box.tall ? { left: 160, top: 640 } : { left: Math.max(40, box.left - 56), top: box.top + box.height - 80 });
  tl.fromTo(
    e,
    { clipPath: 'inset(0 100% 0 0 round 22px)' },
    { clipPath: 'inset(0 0% 0 0 round 22px)', duration: 0.6, ease: 'expo.out' },
    at,
  );
  reveal(e.querySelector('.t'), at, 0.04);
  tl.to(
    e,
    {
      clipPath: 'inset(0 0% 0 100% round 22px)',
      duration: 0.35,
      ease: 'expo.in',
    },
    out,
  );
}

function fit([w, h], maxW, maxH) {
  const k = Math.min(maxW / w, maxH / h);
  return { width: w * k, height: h * k };
}

function screenBox(size, maxW, maxH, top) {
  if (size[0] / size[1] >= 0.8) {
    const f = fit(size, maxW, maxH);
    return { left: (1920 - f.width) / 2, top, ...f, tall: false };
  }
  const f = fit(size, 760, 940);
  return { left: 1920 - f.width - 280, top: 40, ...f, tall: true };
}

function side(s, root, box) {
  if (!box.tall) return;
  const e = $('div', 'side', root, `<div class="kick">${pad2(s.num)}${s.who ? ` — ${s.who}` : ''}</div><div class="big">${s.label}</div>`);
  reveal(e.querySelector('.kick'), s.start + CARD + 0.1);
  reveal(e.querySelector('.big'), s.start + CARD + 0.2, 0.06);
}

const players = [];
function clipScene(s, root) {
  const [vw, vh] = s.clips[0].size;
  const box = screenBox([vw, vh], 1504, 940, 26);
  const { width: W, height: H } = box;
  const k = W / vw;
  side(s, root, box);
  const vp = $('div', 'viewport', root);
  gsap.set(vp, box);
  const screen = $('div', 'screen', vp);
  s.clips.forEach((c, i) => {
    const layer = $('div', 'clip', screen);
    const img = $('img', '', layer);
    gsap.set(img, { width: vw, height: vh });
    const start = s.start + c.at;
    const end = start + c.dur;
    players.push({ img, start, c, k, W, H, shown: '' });
    tl.set(layer, { opacity: 1 }, i === 0 ? s.start : start);
    if (i < s.clips.length - 1) tl.set(layer, { opacity: 0 }, end);
    const out = i < s.clips.length - 1 ? end - 0.3 : s.start + s.dur - 0.35;
    slab(root, box, i + 1, c.caption, c.speed, Math.max(start + 0.15, s.start + CARD + 0.3), out);
  });
}

function shotScene(s, root) {
  const box = screenBox(s.shots[0].size, 1248, 780, 118);
  const { width: CW, height: CH } = box;
  side(s, root, box);
  const card = $('div', 'screen', root);
  gsap.set(card, box);
  const cam = $('div', 'cam', card);
  gsap.set(cam, { width: CW, height: CH });
  const pill = $('div', 'pill', root, `<span class="n">${pad2(s.num)}</span><span class="t">${s.label}</span>`);
  gsap.set(pill, { left: box.left, top: 30, display: box.tall ? 'none' : 'flex' });
  tl.from(card, { scale: 0.94, y: 40, duration: 0.9, ease: 'expo.out' }, s.start + CARD - 0.05);
  tl.from(pill, { opacity: 0, x: -30, duration: 0.6, ease: 'expo.out' }, s.start + CARD + 0.25);
  const cursor = $(
    'div',
    'cursor',
    cam,
    '<svg viewBox="0 0 24 24" width="38" height="38"><path d="M4 2l16 11.5-7.2 1.3 4.3 7.7-3 1.6-4.3-7.8L4 21z" fill="#111" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>',
  );
  const ripple = $('div', 'ripple', cam);
  gsap.set(cursor, {
    x: CW * 0.72,
    y: CH * 0.9,
    opacity: 0,
    transformOrigin: '7px 4px',
  });
  let img = null;
  let captions = 0;
  s.shots.forEach((sh, i) => {
    const at = s.start + sh.at;
    const end = at + sh.dur;
    const k = CW / sh.frame;
    const prev = s.shots[i - 1];
    const next = s.shots[i + 1];
    if (prev?.src !== sh.src) {
      const old = img;
      img = $('img', '', cam);
      img.src = sh.src;
      gsap.set(img, { width: CW, height: CH });
      cam.insertBefore(img, cursor);
      if (!old) tl.set(img, { opacity: 1 }, s.start);
      else {
        tl.to(img, { opacity: 1, duration: 0.4, ease: 'power1.inOut' }, at);
        tl.set(old, { opacity: 0 }, at + 0.4);
      }
    }
    if (sh.caption !== prev?.caption) {
      captions += 1;
      let last = i;
      while (s.shots[last + 1]?.caption === sh.caption) last += 1;
      const until = last === s.shots.length - 1 ? s.start + s.dur - 0.35 : s.start + s.shots[last].at + s.shots[last].dur - 0.3;
      slab(root, box, captions, sh.caption, 1, Math.max(at + 0.1, s.start + CARD + 0.35), until);
    }
    let t = at + (prev?.src === sh.src ? 0.1 : 0.45);
    if (sh.click) {
      const cx = (sh.click.x + sh.click.w / 2) * k;
      const cy = (sh.click.y + sh.click.h / 2) * k;
      tl.to(cursor, { opacity: 1, duration: 0.25 }, t);
      tl.to(cursor, { x: cx, y: cy, duration: 0.9, ease: 'power2.inOut' }, t);
      tl.to(cursor, { scale: 0.82, duration: 0.1, yoyo: true, repeat: 1 }, t + 0.95);
      tl.set(ripple, { x: cx, y: cy }, t + 0.95);
      tl.fromTo(ripple, { opacity: 1, scale: 0.3 }, { opacity: 0, scale: 1.7, duration: 0.6, ease: 'power2.out' }, t + 0.95);
      t += 1.3;
    }
    if (!sh.zoom) return;
    const zw = sh.zoom.w * k;
    const zh = sh.zoom.h * k;
    const z = Math.min(2.2, (CW * 0.85) / zw, (CH * 0.85) / zh);
    if (z < 1.15) return;
    const zx = (sh.zoom.x + sh.zoom.w / 2) * k;
    const zy = (sh.zoom.y + sh.zoom.h / 2) * k;
    const dx = Math.min(0, Math.max(CW - CW * z, CW / 2 - z * zx));
    const dy = Math.min(0, Math.max(CH - CH * z, CH / 2 - z * zy));
    tl.to(cursor, { opacity: 0, duration: 0.25 }, t);
    tl.to(cam, { scale: z, x: dx, y: dy, duration: 0.85, ease: 'power3.inOut' }, t);
    const keep = next?.src === sh.src && next.zoom && !next.click;
    if (!keep) tl.to(cam, { scale: 1, x: 0, y: 0, duration: 0.65, ease: 'power3.inOut' }, end - 0.7);
  });
}

const builders = {
  intro(s, root) {
    const c = $('div', 'center', root);
    if (s.title) {
      const lk = $(
        'div',
        'lockup',
        c,
        `${logo('a', s.logoHeight ?? 250)}${s.kicker ? `<div class="kick">${s.kicker}</div>` : ''}<h1>${s.title}</h1>`,
      );
      const mark = lk.querySelector('img');
      tl.from(
        mark,
        {
          scale: 0.35,
          rotation: -40,
          opacity: 0,
          duration: 1.1,
          ease: 'back.out(1.5)',
        },
        s.start + 0.15,
      );
      if (s.kicker) reveal(lk.querySelector('.kick'), s.start + 0.8);
      reveal(lk.querySelector('h1'), s.start + 0.95, 0.09);
      tl.to(lk, { scale: 1.04, duration: s.dur, ease: 'none' }, s.start);
      return;
    }
    const row = $('div', 'logos', c, lockup(s.logoHeight ?? 190));
    const parts = [...row.children];
    tl.from(parts[0], { opacity: 0, scale: 0.8, duration: 0.8, ease: 'back.out(1.6)' }, s.start + 0.15);
    if (parts[1]) tl.from(parts[1], { opacity: 0, scale: 0.3, duration: 0.5, ease: 'back.out(2)' }, s.start + 1.2);
    if (parts[2])
      tl.fromTo(
        parts[2],
        { clipPath: 'inset(0 100% 0 0)' },
        { clipPath: 'inset(0 0% 0 0)', duration: 1.0, ease: 'power2.inOut' },
        s.start + 1.4,
      );
  },
  statement(s, root) {
    const c = $('div', 'center', root);
    reveal($('h1', '', c, s.title), s.start + 0.1);
    if (s.sub) popIn($('div', 'sub', c, s.sub), s.start + 0.9);
    if (s.cards) {
      const row = $('div', 'cards', c);
      s.cards.forEach((x, i) => {
        const el = $('div', 'card', row, `<div class="chip"><i></i>${x.tag}</div><div class="say">${x.text}</div>`);
        const t = s.start + 1.4 + i * 1.3;
        tl.fromTo(
          el,
          { clipPath: 'inset(100% 0 0 0 round 28px)', y: 40 },
          {
            clipPath: 'inset(0% 0 0 0 round 28px)',
            y: 0,
            duration: 0.8,
            ease: 'expo.out',
          },
          t,
        );
        tl.from(el.querySelector('.chip'), { scale: 0.4, opacity: 0, duration: 0.5, ease: 'back.out(2)' }, t + 0.35);
        reveal(el.querySelector('.say'), t + 0.3, 0.04);
      });
    }
    if (!s.bands) return;
    const wrap = $('div', 'bands', c);
    const rows = s.bands.map((b) =>
      $(
        'div',
        `band ${b.accent ? 'accent' : ''}`,
        wrap,
        `<div><div class="kind">${b.kind}</div><div class="logo">${logo(b.logo, 58)}</div></div><ul>${b.items.map((t) => `<li>${t}</li>`).join('')}</ul>`,
      ),
    );
    popIn(rows, s.start + 1.0, { y: 40, stagger: 0.2 });
    tl.from(wrap.querySelectorAll('li'), { opacity: 0, x: -14, duration: 0.4, ease: 'power2.out', stagger: 0.08 }, s.start + 1.5);
  },
  title(s, root) {
    if (s.card) {
      const c = $('div', 'chapcard', root, `<div class="kick">${s.kicker ?? ''}</div><div class="big">${s.text}</div>`);
      reveal(c.querySelector('.kick'), s.start + 0.1);
      reveal(c.querySelector('.big'), s.start + 0.2, 0.09);
      return;
    }
    const c = $('div', 'center', root);
    const h = $('h1', 'huge', c, s.text);
    const rule = $('div', 'rule', c);
    reveal(h, s.start + 0.05, 0.09);
    tl.from(rule, { scaleX: 0, transformOrigin: '0 50%', duration: 0.7, ease: 'expo.out' }, s.start + 0.45);
  },
  app(s, root) {
    chapter(s, root);
    if (s.shots) shotScene(s, root);
    else clipScene(s, root);
  },
  flow(s, root) {
    const head = $('div', 'head', root);
    reveal($('h1', '', head, s.text), s.start + 0.1, 0.06);
    const n = s.nodes.length;
    const gap = 120;
    const w = Math.min(440, (1560 - (n - 1) * gap) / n);
    const left = (1920 - (n * w + (n - 1) * gap)) / 2;
    const svg = svgEl('svg', { class: 'lines', viewBox: '0 0 1920 1080' }, root);
    s.nodes.forEach((node, i) => {
      const x = left + i * (w + gap);
      const mark = node.logo ? logo(node.logo, 84) : '';
      const rows = (node.rows ?? []).map(([a, b]) => `<div class="row">${a}<b>${b}</b></div>`).join('');
      const el = $(
        'div',
        `node${node.hero ? ' hero' : ''}`,
        root,
        `${mark}<div class="name">${node.name}</div><div class="note">${node.note ?? ''}</div><div class="rows">${rows}</div>`,
      );
      gsap.set(el, { left: x, width: w });
      const at = s.start + 0.9 + i * 1.3;
      tl.from(el, { opacity: 0, y: 80, scale: 0.94, duration: 0.9, ease: 'expo.out' }, at);
      tl.from(el.children, { opacity: 0, y: 24, duration: 0.6, ease: 'power3.out', stagger: 0.08 }, at + 0.2);
      if (node.badge) {
        const badge = $('div', 'badge', root, `<i></i>${node.badge}`);
        gsap.set(badge, { left: x + 44, top: 370 });
        tl.from(badge, { scale: 0.3, opacity: 0, duration: 0.6, ease: 'back.out(2.2)' }, s.start + 1.3 * n + 0.4);
      }
      if (i === 0) return;
      const x0 = x - gap + 6;
      const x1 = x - 6;
      const line = svgEl('path', { d: `M${x0} 590 L${x1} 590`, class: 'stroke' }, svg);
      const tip = svgEl('path', { d: `M${x1 - 18} 576 L${x1} 590 L${x1 - 18} 604`, class: 'stroke' }, svg);
      draw(line, at - 0.35, 0.5);
      draw(tip, at - 0.05, 0.3);
      const dot = svgEl('circle', { cx: x0, cy: 590, r: 9, class: 'dot' }, svg);
      const from = at + 0.3;
      const reps = Math.max(0, Math.floor((s.start + s.dur - from) / 1.1) - 1);
      tl.fromTo(
        dot,
        { x: 0, opacity: 0 },
        {
          x: x1 - x0 - 20,
          opacity: 1,
          duration: 1.1,
          ease: 'power1.inOut',
          repeat: reps,
        },
        from,
      );
    });
  },
  loop(s, root) {
    const head = $('div', 'head', root);
    gsap.set(head, { top: 90 });
    reveal($('h1', '', head, s.text), s.start + 0.1, 0.06);
    const [cx, cy, rx, ry] = [960, 610, 560, 262];
    const at = (a) => [cx + rx * Math.cos(a), cy + ry * Math.sin(a)];
    const svg = svgEl('svg', { class: 'lines', viewBox: '0 0 1920 1080' }, root);
    svgEl('ellipse', { cx, cy, rx, ry, class: 'track' }, svg);
    const ring = svgEl(
      'path',
      {
        d: `M${cx} ${cy - ry} A${rx} ${ry} 0 1 1 ${cx - 0.01} ${cy - ry}`,
        class: 'stroke',
      },
      svg,
    );
    const n = s.nodes.length;
    const step = (Math.PI * 2) / n;
    const a0 = -Math.PI / 2;
    const mark = $('div', 'loopmark', root, logo('a', 150));
    tl.from(mark, { scale: 0.4, opacity: 0, duration: 0.8, ease: 'back.out(1.6)' }, s.start + 0.5);
    draw(ring, s.start + 0.7, 3.2);
    s.nodes.forEach((text, i) => {
      const [x, y] = at(a0 + i * step);
      const e = $('div', `lnode${i === s.you ? ' you' : ''}`, root, `<span class="k">${i + 1}</span>${text}`);
      gsap.set(e, { left: x, top: y });
      tl.from(e, { scale: 0.5, opacity: 0, duration: 0.6, ease: 'back.out(1.8)' }, s.start + 0.7 + (3.2 * i) / n);
      const a = a0 + (i + 0.5) * step;
      const [ax, ay] = at(a);
      const angle = (Math.atan2(ry * Math.cos(a), -rx * Math.sin(a)) * 180) / Math.PI;
      const arrow = svgEl(
        'path',
        {
          d: 'M-11 -13 L7 0 L-11 13',
          class: 'stroke',
          transform: `translate(${ax} ${ay}) rotate(${angle})`,
        },
        svg,
      );
      tl.from(arrow, { opacity: 0, duration: 0.3 }, s.start + 0.7 + (3.2 * (i + 0.5)) / n);
    });
    const dot = svgEl('circle', { r: 13, class: 'dot' }, svg);
    const length = ring.getTotalLength();
    const pos = { p: 0 };
    const place = () => {
      const q = ring.getPointAtLength((((pos.p % 1) + 1) % 1) * length);
      dot.setAttribute('cx', q.x);
      dot.setAttribute('cy', q.y);
    };
    place();
    gsap.set(dot, { opacity: 0 });
    tl.set(dot, { opacity: 1 }, s.start + 3.9);
    tl.fromTo(
      pos,
      { p: 0 },
      {
        p: Math.max(1, Math.floor((s.dur - 3.9) / 3.4)),
        duration: s.dur - 3.9 + FADE,
        ease: 'none',
        onUpdate: place,
      },
      s.start + 3.9,
    );
    if (s.badge == null) return;
    const [bx, by] = at(a0 + s.you * step);
    const badge = $('div', 'badge', root, `<i></i>${s.badge}`);
    gsap.set(badge, { left: bx - 130, top: by + 50 });
    tl.from(badge, { scale: 0.3, opacity: 0, duration: 0.6, ease: 'back.out(2.2)' }, s.start + 4.3);
  },
  collage(s, root) {
    const c = $('div', 'center', root);
    const h = $('h1', 'over', c, s.text);
    const spots = [
      [70, 64, -2],
      [1290, 64, 2],
      [70, 700, 2],
      [1290, 700, -2],
    ];
    const cards = s.shots.slice(0, 4).map((src, i) => {
      const d = $('div', 'collage', root, `<img src="../${src}" alt="">`);
      gsap.set(d, {
        left: spots[i][0],
        top: spots[i][1],
        rotation: spots[i][2],
      });
      return d;
    });
    reveal(h, s.start + 0.1);
    tl.from(
      cards,
      {
        opacity: 0,
        y: (i) => (i < 2 ? -160 : 160),
        rotation: 0,
        duration: 1.0,
        ease: 'expo.out',
        stagger: 0.09,
      },
      s.start + 0.25,
    );
    tl.to(cards, { y: '-=14', duration: s.dur + FADE, ease: 'none' }, s.start);
  },
  outro(s, root) {
    const c = $('div', 'center', root);
    const row = s.title
      ? $('div', 'lockup', c, `${logo('a', 200)}<div class="kick">${s.kicker ?? ''}</div><h1>${s.title}</h1>`)
      : $('div', 'logos', c, lockup(s.logoHeight ?? 160));
    popIn(row, s.start + 0.1);
    if (s.text) reveal($('div', 'tag', c, s.text), s.start + 0.6, 0.05);
    if (s.cta)
      tl.from(
        $('div', 'cta', c, s.cta),
        {
          clipPath: 'inset(0 100% 0 0 round 999px)',
          duration: 0.8,
          ease: 'expo.inOut',
        },
        s.start + 1.4,
      );
  },
};

function subtitles(s) {
  const box = document.getElementById('subs');
  s.subs.forEach((x, i) => {
    const e = $('div', 'subline', box, x.text);
    const next = s.subs[i + 1];
    const joined = next && next.at - (x.at + x.dur) < 0.05;
    tl.fromTo(e, { opacity: 0, y: 10 }, { opacity: 1, y: 0, duration: 0.22, ease: 'power2.out' }, x.at);
    tl.to(e, { opacity: 0, duration: 0.18 }, joined ? x.at + x.dur - 0.18 : x.at + x.dur + 0.3);
  });
}

function backdrop(total) {
  const bg = document.getElementById('backdrop');
  bg.hidden = false;
  const blobs = [
    [-160, -220, 820, 220, 140],
    [1250, 520, 900, -260, -120],
    [640, 760, 700, 180, -180],
  ];
  for (const [x, y, size, dx, dy] of blobs) {
    const e = $('div', 'blob', bg);
    gsap.set(e, { left: x, top: y, width: size, height: size });
    tl.to(e, { x: dx, y: dy, duration: total, ease: 'sine.inOut' }, 0);
  }
  tl.to(bg.querySelector('.grid'), { x: -32, y: -64, duration: total, ease: 'none' }, 0);
}

function paintClips(t) {
  const loads = [];
  for (const p of players) {
    const f = Math.max(0, Math.min(p.c.frames - 1, Math.floor((t - p.start) * 30)));
    const [z, cx, cy] = p.c.cam[f];
    const src = `${p.c.src}${String(p.c.files[f]).padStart(5, '0')}.jpg`;
    if (p.shown !== src) {
      p.img.src = src;
      p.shown = src;
      loads.push(p.img.decode().catch(() => {}));
    }
    p.img.style.transform = `translate(${p.W / 2 - cx * z * p.k}px, ${p.H / 2 - cy * z * p.k}px) scale(${z * p.k})`;
  }
  return Promise.all(loads);
}

window.ready = (async () => {
  const root = document.documentElement.style;
  for (const [name, value] of Object.entries(B.colors ?? {})) root.setProperty(`--${name}`, value);
  if (B.displayWeight) root.setProperty('--weight', B.displayWeight);
  for (const [family, file] of [
    ['Display', B.font],
    ['Body', B.bodyFont],
  ]) {
    if (file)
      document.fonts.add(
        await new FontFace(family, `url(../${file})`, {
          weight: '100 900',
        }).load(),
      );
  }
  const total = window.SCENES.reduce((m, s) => Math.max(m, s.start + s.dur), 0);
  if (OPT.backdrop) backdrop(total);
  window.SCENES.forEach((s, i) => {
    builders[s.type](s, sceneRoot(s, i));
    if (OPT.subtitles) subtitles(s);
  });
  tl.seek(0);
  await paintClips(0);
  await document.fonts.ready;
  await Promise.all([...document.images].map((i) => i.decode().catch(() => {})));
  return total;
})();
window.seek = (t) => {
  tl.seek(t, false);
  return paintClips(t);
};
