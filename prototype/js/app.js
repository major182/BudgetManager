/*
 * プロトタイプの共通処理。
 * 実装では Django のテンプレートと htmx で作る部分を、ここでは JavaScript で真似ている。
 * 消費税の計算（calcTax）も、実装ではサーバーで行う（画面設計書 4.2、技術選定書 5.3）。
 */
(function () {
  const P = window.PROTO;

  // ---------------------------------------------------------------- 基本
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  // 利用者が入力した文字を HTML に埋め込むときは必ず無害化する（S-02 と同じ考え方）
  const esc = (s) =>
    String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

  const params = new URLSearchParams(location.search);

  // ---------------------------------------------------------------- 表示の形（画面設計書 1.3）
  const yen = (n, opt = {}) => {
    const abs = Math.abs(n).toLocaleString("ja-JP");
    let sign = "";
    if (opt.sign === "+") sign = "＋";
    else if (opt.sign === "-") sign = "−";
    else if (n < 0) sign = "−";
    return `${sign}¥${abs}`;
  };
  const plain = (n) => (n < 0 ? "−" : "") + Math.abs(n).toLocaleString("ja-JP");

  const WD = ["日", "月", "火", "水", "木", "金", "土"];
  const toDate = (s) => {
    const [y, m, d] = s.split("-").map(Number);
    return new Date(y, m - 1, d);
  };
  const fmt = (dt) =>
    `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}-${String(dt.getDate()).padStart(2, "0")}`;
  const md = (s) => {
    const d = toDate(s);
    return `${d.getMonth() + 1}/${d.getDate()}（${WD[d.getDay()]}）`;
  };
  const ym = (s) => {
    const [y, m] = s.split("-").map(Number);
    return `${y}年${m}月`;
  };
  const addMonth = (s, k) => {
    const [y, m] = s.split("-").map(Number);
    const d = new Date(y, m - 1 + k, 1);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
  };

  // ---------------------------------------------------------------- データの参照
  const cat = (id) => P.categories.find((c) => c.id === id);
  const catLabel = (id) => {
    const c = cat(id);
    if (!c) return "";
    return c.parent ? `${cat(c.parent).name}／${c.name}` : c.name;
  };
  const topCat = (id) => {
    const c = cat(id);
    return c.parent ? c.parent : c.id;
  };
  const asset = (id) => P.assets.find((a) => a.id === id);
  const txById = (id) => P.tx.find((t) => t.id === id);

  // 明細の金額（収入・支出は内訳の税込額の合計。DB 設計書 3.1）
  const amountOf = (t) => (t.kind === "transfer" ? t.amount : t.lines.reduce((s, l) => s + l.amt, 0));

  const inMonth = (t, month) => t.date.startsWith(month);
  const txIn = (month) => P.tx.filter((t) => inMonth(t, month));

  const totals = (list) => {
    let income = 0;
    let expense = 0;
    for (const t of list) {
      if (t.kind === "income") income += amountOf(t);
      if (t.kind === "expense") expense += amountOf(t);
    }
    return { income, expense, diff: income - expense };
  };

  // 資産の残高（DB 設計書 5.3）
  const balance = (assetId, upto = P.TODAY) => {
    const a = asset(assetId);
    let b = a.opening;
    for (const t of P.tx) {
      if (t.date > upto) continue;
      const amt = amountOf(t);
      if (t.kind === "income" && t.asset === assetId) b += amt;
      if (t.kind === "expense" && t.asset === assetId) b -= amt;
      if (t.kind === "transfer" && t.asset === assetId) b -= amt;
      if (t.kind === "transfer" && t.to === assetId) b += amt;
    }
    return b;
  };

  // 消費税の計算（DB 設計書 5.6）。実装ではサーバーで行う
  const calcTax = (lines, inputType) => {
    const groups = new Map();
    lines.forEach((l, i) => {
      if (!Number.isFinite(l.amt) || l.amt === 0) return;
      if (!groups.has(l.rate)) groups.set(l.rate, []);
      groups.get(l.rate).push({ ...l, i });
    });
    const rows = [];
    const perLine = [];
    for (const [rate, ls] of [...groups.entries()].sort((a, b) => a[0] - b[0])) {
      const sign = ls[0].amt < 0 ? -1 : 1;
      const sum = ls.reduce((s, l) => s + Math.abs(l.amt), 0);
      const tax =
        inputType === "incl" ? Math.floor((sum * rate) / (100 + rate)) : Math.floor((sum * rate) / 100);
      // まとまりの税額を、金額の割合で内訳へ割り振る（余りは最も大きい内訳へ）
      let given = 0;
      const shares = ls.map((l) => {
        const t = Math.floor((Math.abs(l.amt) * tax) / sum);
        given += t;
        return t;
      });
      let maxIdx = 0;
      ls.forEach((l, k) => {
        if (Math.abs(l.amt) > Math.abs(ls[maxIdx].amt)) maxIdx = k;
      });
      shares[maxIdx] += tax - given;
      ls.forEach((l, k) => {
        const a = Math.abs(l.amt);
        const incl = inputType === "incl" ? a : a + shares[k];
        perLine[l.i] = { excl: sign * (incl - shares[k]), tax: sign * shares[k], incl: sign * incl };
      });
      const incl = inputType === "incl" ? sum : sum + tax;
      rows.push({ rate, excl: sign * (incl - tax), tax: sign * tax, incl: sign * incl });
    }
    const total = rows.reduce(
      (s, r) => ({ excl: s.excl + r.excl, tax: s.tax + r.tax, incl: s.incl + r.incl }),
      { excl: 0, tax: 0, incl: 0 },
    );
    return { rows, total, perLine };
  };

  // ---------------------------------------------------------------- テーマ（F-CF-04）
  const applyTheme = () => {
    let t = "dark";
    try {
      t = localStorage.getItem("proto-theme") || "dark";
    } catch (e) {
      /* 保存できない環境では既定のダーク */
    }
    const actual = t === "system" ? (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark") : t;
    document.documentElement.dataset.theme = actual;
  };
  applyTheme();

  // ---------------------------------------------------------------- アイコン
  const ICON = {
    book: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2z"/><path d="M4 19V5"/><path d="M8 7h7M8 11h7"/></svg>',
    chart: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="12" r="8"/><path d="M12 4v8l6 5"/></svg>',
    wallet: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><rect x="3" y="6" width="18" height="13" rx="2"/><path d="M3 10h18M16 14.5h2"/></svg>',
    gear: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1"/></svg>',
    prev: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 6l-6 6 6 6"/></svg>',
    next: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 6l6 6-6 6"/></svg>',
    search: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/></svg>',
    plus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>',
    close: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>',
    up: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 15l6-6 6 6"/></svg>',
    down: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg>',
    trend: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 17l6-6 4 4 8-8"/><path d="M15 7h6v6"/></svg>',
    calc: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><rect x="5" y="3" width="14" height="18" rx="2"/><path d="M8 7h8M8 12h.01M12 12h.01M16 12h.01M8 16h.01M12 16h.01M16 16h.01"/></svg>',
  };

  // ---------------------------------------------------------------- 骨組み（画面設計書 1.1）
  const renderNav = (active) => {
    const items = [
      ["book", "家計簿", "ledger.html", "ledger"],
      ["chart", "統計", "stats.html", "stats"],
      ["wallet", "資産", "assets.html", "assets"],
      ["gear", "設定", "settings.html", "settings"],
    ];
    const nav = document.createElement("nav");
    nav.className = "nav";
    nav.setAttribute("aria-label", "メニュー");
    nav.innerHTML =
      '<span class="brand">家計簿</span>' +
      items
        .map(
          ([ic, label, href, key]) =>
            `<a href="${href}"${key === active ? ' aria-current="page"' : ""}>${ICON[ic]}<span>${label}</span></a>`,
        )
        .join("");
    document.body.prepend(nav);
  };

  // ---------------------------------------------------------------- 知らせ・確認（画面設計書 1.6）
  const toast = (msg) => {
    const el = document.createElement("div");
    el.className = "toast";
    el.setAttribute("role", "status");
    el.textContent = msg;
    document.body.append(el);
    setTimeout(() => el.remove(), 2200);
  };

  const confirmDialog = (msg, okLabel, cancelLabel = "キャンセル") =>
    new Promise((resolve) => {
      const d = document.createElement("dialog");
      d.className = "confirm";
      d.innerHTML = `<p>${esc(msg)}</p><div class="btn-row"><button class="btn" value="no">${esc(cancelLabel)}</button><button class="btn danger" value="yes">${esc(okLabel)}</button></div>`;
      document.body.append(d);
      d.addEventListener("click", (e) => {
        const v = e.target.closest("button")?.value;
        if (!v) return;
        d.close();
        d.remove();
        resolve(v === "yes");
      });
      d.showModal();
    });

  // 明細入力を開く：スマホは画面全体、PC は重ねた小窓（画面設計書 1.7）
  const openEntry = (query = "") => {
    const d = document.createElement("dialog");
    d.className = "sheet";
    d.innerHTML = `<iframe src="transaction.html?embed=1${query ? "&" + query : ""}" title="明細の入力"></iframe>`;
    document.body.append(d);
    d.showModal();
    const onMsg = (e) => {
      if (!e.data || e.data.type !== "entry") return;
      window.removeEventListener("message", onMsg);
      d.close();
      d.remove();
      if (e.data.message) toast(e.data.message);
    };
    window.addEventListener("message", onMsg);
    d.addEventListener("cancel", () => window.removeEventListener("message", onMsg));
  };

  // ---------------------------------------------------------------- 明細の行（日別・検索・資産詳細で共通）
  const txRow = (t, opt = {}) => {
    const amt = amountOf(t);
    let catText;
    let sub;
    let cls;
    let sign;
    if (t.kind === "transfer") {
      catText = "振替";
      sub = `${esc(t.desc)}　${esc(asset(t.asset).name)} → ${esc(asset(t.to).name)}`;
      cls = "transfer";
      sign = "";
    } else {
      catText = esc(catLabel(t.lines[0].cat)) + (t.lines.length > 1 ? ` <span class="muted">他${t.lines.length - 1}件</span>` : "");
      sub = `${esc(t.desc)}　${esc(asset(t.asset).name)}`;
      const plus = t.kind === "income" || amt < 0;
      cls = plus ? "income" : "expense";
      sign = plus ? "+" : "-";
    }
    let amtText = t.kind === "transfer" ? yen(amt) : yen(amt, { sign });
    if (opt.assetId) {
      // 資産詳細では、その資産から見た増減で表示する
      const out = (t.kind === "expense" && t.asset === opt.assetId) || (t.kind === "transfer" && t.asset === opt.assetId);
      const v = out ? -amt : amt;
      amtText = yen(v, { sign: v < 0 ? "-" : "+" });
      // 振替は増減にかかわらず灰色（画面設計書 1.2）
      cls = t.kind === "transfer" ? "transfer" : v < 0 ? "expense" : "income";
    }
    const badge = t.recurring ? '<span class="badge">定期</span>' : "";
    const after = opt.after !== undefined ? `<div class="sub num">残高 ${plain(opt.after)}</div>` : "";
    return `<div class="row" data-tx="${t.id}" role="button" tabindex="0">
      <div class="cat">${catText}${badge}</div>
      <div class="sub">${sub}</div>
      <div class="amt num ${cls}">${amtText}</div>${after}
    </div>`;
  };

  const bindRows = (root, onChange) => {
    root.addEventListener("click", (e) => {
      const r = e.target.closest("[data-tx]");
      if (r) openEntry(`id=${r.dataset.tx}`);
    });
    if (onChange) window.addEventListener("focus", onChange);
  };

  const dayGroups = (list) => {
    const byDate = new Map();
    [...list]
      .sort((a, b) => (a.date === b.date ? b.id - a.id : a.date < b.date ? 1 : -1))
      .forEach((t) => {
        if (!byDate.has(t.date)) byDate.set(t.date, []);
        byDate.get(t.date).push(t);
      });
    return [...byDate.entries()]
      .map(([date, ts]) => {
        const s = totals(ts);
        const d = toDate(date);
        const wcls = d.getDay() === 6 ? "sat" : d.getDay() === 0 || P.holidays[date] ? "sun" : "";
        return `<section class="day">
          <div class="day-head"><span class="d">${d.getDate()}</span><span class="w ${wcls}">${WD[d.getDay()]}</span>
            <span class="muted">${d.getMonth() + 1}月</span>
            <span class="sums num">${s.income ? `<span class="income">${yen(s.income)}</span>` : ""}${s.expense ? `<span class="expense">${yen(s.expense)}</span>` : ""}</span>
          </div>
          ${ts.map((t) => txRow(t)).join("")}
        </section>`;
      })
      .join("");
  };

  // ================================================================ SC-01 家計簿
  const pageLedger = () => {
    renderNav("ledger");
    let view = params.get("view") || "daily";
    let month = params.get("month") || P.TODAY.slice(0, 7);
    let selected = P.TODAY;
    const main = $("#main");

    const render = () => {
      const list = txIn(month);
      const year = month.slice(0, 4);
      const isYear = view === "monthly";
      const s = isYear
        ? P.tx.filter((t) => t.date.startsWith(year)).reduce(
            (acc, t) => {
              const x = totals([t]);
              return { income: acc.income + x.income, expense: acc.expense + x.expense, diff: acc.diff + x.diff };
            },
            { income: 0, expense: 0, diff: 0 },
          )
        : totals(list);
      if (isYear) {
        // 過去の月は集計済みのダミーの値を足す
        P.history.months.forEach((m, i) => {
          if (m.startsWith(year)) {
            s.income += P.history.income[i];
            s.expense += P.history.expense[i];
          }
        });
        s.diff = s.income - s.expense;
      }

      let body = "";
      if (view === "daily") {
        body = list.length ? dayGroups(list) : '<div class="empty">この期間の明細はありません。</div>';
      } else if (view === "calendar") {
        body = calendar(month, list);
      } else {
        body = monthly(year);
      }

      main.innerHTML = `
        <header class="header">
          <button class="icon-btn" data-go="-1" aria-label="前へ">${ICON.prev}</button>
          <div class="period"><span class="label">${isYear ? `${year}年` : ym(month)}</span></div>
          <button class="icon-btn" data-go="1" aria-label="次へ">${ICON.next}</button>
          <a class="icon-btn" href="search.html" aria-label="検索">${ICON.search}</a>
        </header>
        <div class="totals">
          <div><div class="cap">収入</div><div class="val num income">${yen(s.income)}</div></div>
          <div><div class="cap">支出</div><div class="val num expense">${yen(s.expense)}</div></div>
          <div><div class="cap">合計</div><div class="val num">${yen(s.diff)}</div></div>
        </div>
        <nav class="tabs" role="tablist">
          ${[["daily", "日別"], ["calendar", "カレンダー"], ["monthly", "月別"]]
            .map(([k, l]) => `<button role="tab" data-view="${k}" aria-selected="${k === view}">${l}</button>`)
            .join("")}
        </nav>
        <div id="body">${body}</div>
        <div class="proto-note">プロトタイプ：データがあるのは 2026年10月だけです。「今日」は 2026-10-15 に固定しています。</div>`;
      history.replaceState(null, "", `?view=${view}&month=${month}`);
    };

    const calendar = (m, list) => {
      const [y, mo] = m.split("-").map(Number);
      const first = new Date(y, mo - 1, 1);
      const start = new Date(first);
      start.setDate(1 - first.getDay()); // 週の開始は日曜（BR-22 の初期値）
      const cells = [];
      for (let i = 0; i < 42; i++) {
        const d = new Date(start);
        d.setDate(start.getDate() + i);
        if (i >= 35 && d.getMonth() !== mo - 1) break;
        const key = fmt(d);
        const s = totals(list.filter((t) => t.date === key));
        const short = (n) => (n >= 10000 ? `${(n / 10000).toFixed(1).replace(/\.0$/, "")}万` : n.toLocaleString("ja-JP"));
        const cls = [
          d.getMonth() !== mo - 1 ? "out" : "",
          d.getDay() === 6 ? "sat" : "",
          d.getDay() === 0 || P.holidays[key] ? "sun" : "",
          key === P.TODAY ? "today" : "",
        ].join(" ");
        cells.push(`<button class="cal-cell ${cls}" data-date="${key}" aria-selected="${key === selected}">
          <span class="n">${d.getDate()}</span>
          ${s.income ? `<span class="income num">${short(s.income)}</span>` : ""}
          ${s.expense ? `<span class="expense num">${short(s.expense)}</span>` : ""}
        </button>`);
      }
      const dayList = list.filter((t) => t.date === selected);
      return `<div class="cal"><div class="cal-grid">
          ${WD.map((w, i) => `<div class="wd ${i === 6 ? "sat" : i === 0 ? "sun" : ""}">${w}</div>`).join("")}
          ${cells.join("")}
        </div></div>
        <div class="list-caption">${md(selected)}${P.holidays[selected] ? `　${P.holidays[selected]}` : ""} の明細</div>
        ${dayList.length ? `<section class="day">${dayList.map((t) => txRow(t)).join("")}</section>` : '<div class="empty">この日の明細はありません。</div>'}`;
    };

    const monthly = (year) => {
      const rows = [];
      for (let mo = 12; mo >= 1; mo--) {
        const m = `${year}-${String(mo).padStart(2, "0")}`;
        let s;
        const hi = P.history.months.indexOf(m);
        if (m === "2026-10") s = totals(txIn(m));
        else if (hi >= 0) s = { income: P.history.income[hi], expense: P.history.expense[hi] };
        else continue;
        rows.push(`<div class="mrow" data-month="${m}" role="button" tabindex="0">
          <span class="m">${mo}月</span><span class="num">${yen(s.income - s.expense)}</span>
          <div class="nums num"><span class="income">${yen(s.income, { sign: "+" })}</span><span class="expense">${yen(s.expense, { sign: "-" })}</span></div>
        </div>`);
      }
      return rows.join("") || '<div class="empty">この期間の明細はありません。</div>';
    };

    main.addEventListener("click", (e) => {
      const go = e.target.closest("[data-go]");
      if (go) {
        month = view === "monthly" ? `${Number(month.slice(0, 4)) + Number(go.dataset.go)}${month.slice(4)}` : addMonth(month, Number(go.dataset.go));
        render();
        return;
      }
      const tab = e.target.closest("[data-view]");
      if (tab) {
        view = tab.dataset.view;
        render();
        return;
      }
      const cell = e.target.closest("[data-date]");
      if (cell) {
        selected = cell.dataset.date;
        render();
        return;
      }
      const mr = e.target.closest("[data-month]");
      if (mr) {
        month = mr.dataset.month;
        view = "daily";
        render();
      }
    });
    bindRows(main);

    const fab = document.createElement("button");
    fab.className = "fab";
    fab.setAttribute("aria-label", "明細を登録");
    fab.innerHTML = ICON.plus;
    fab.addEventListener("click", () => openEntry(view === "calendar" ? `date=${selected}` : ""));
    document.body.append(fab);
    render();
  };

  // ================================================================ SC-02 明細入力
  const pageEntry = () => {
    const embed = params.get("embed") === "1";
    const editId = Number(params.get("id")) || null;
    const copyId = Number(params.get("copy")) || null;
    const src = txById(editId || copyId);
    const mode = editId ? "edit" : copyId ? "copy" : "new";

    const state = {
      kind: src ? src.kind : "expense",
      date: mode === "edit" ? src.date : params.get("date") || P.TODAY,
      asset: src ? src.asset : 1,
      to: src && src.to ? src.to : 1,
      desc: src ? src.desc : "",
      memo: src ? src.memo : "",
      input: "incl",
      amount: src && src.kind === "transfer" ? src.amount : "",
      lines: src && src.lines ? src.lines.map((l) => ({ ...l })) : [{ cat: null, rate: 10, amt: NaN }],
    };
    let dirty = false;
    const main = $("#main");

    const close = (message) => {
      if (embed) parent.postMessage({ type: "entry", message }, "*");
      else location.href = "ledger.html";
    };

    const catOptions = (selectedId) => {
      const tops = P.categories.filter((c) => c.kind === state.kind && !c.parent);
      return (
        `<option value="">選んでください</option>` +
        tops
          .map((c) => {
            const kids = P.categories.filter((k) => k.parent === c.id);
            return (
              `<option value="${c.id}"${c.id === selectedId ? " selected" : ""}>${esc(c.name)}</option>` +
              kids.map((k) => `<option value="${k.id}"${k.id === selectedId ? " selected" : ""}>　└ ${esc(k.name)}</option>`).join("")
            );
          })
          .join("")
      );
    };
    const rateOptions = (r) =>
      P.taxRates.map((t) => `<option value="${t.rate}"${t.rate === r ? " selected" : ""}>${esc(t.name)}</option>`).join("");
    const assetOptions = (id) =>
      P.assets.filter((a) => !a.hidden).map((a) => `<option value="${a.id}"${a.id === id ? " selected" : ""}>${esc(a.name)}</option>`).join("");

    const taxTable = () => {
      const r = calcTax(state.lines, state.input);
      if (!r.rows.length) return '<p class="muted" style="margin:0;font-size:13px">金額を入力すると、税額を計算して表示します。</p>';
      return `<table class="tax-table num"><thead><tr><th></th><th>税抜</th><th>税</th><th>税込</th></tr></thead><tbody>
        ${r.rows.map((x) => `<tr><td>${x.rate}%</td><td>${plain(x.excl)}</td><td>${plain(x.tax)}</td><td>${plain(x.incl)}</td></tr>`).join("")}
        <tr class="total"><td>合計</td><td>${plain(r.total.excl)}</td><td>${plain(r.total.tax)}</td><td>${plain(r.total.incl)}</td></tr>
      </tbody></table>`;
    };

    const title = mode === "edit" ? "明細の編集" : "明細の登録";
    const render = () => {
      const isTransfer = state.kind === "transfer";
      main.innerHTML = `
        <header class="header">
          <button class="icon-btn" id="close" aria-label="閉じる">${ICON.close}</button>
          <h1>${title}</h1>
          <button class="btn primary" id="save" style="min-width:72px">${mode === "edit" ? "保存" : "登録"}</button>
        </header>
        <div class="tabs" role="tablist">
          ${[["expense", "支出"], ["income", "収入"], ["transfer", "振替"]]
            .map(([k, l]) => `<button role="tab" data-kind="${k}" aria-selected="${k === state.kind}">${l}</button>`)
            .join("")}
        </div>
        <div id="form-error"></div>
        <form class="form" onsubmit="return false">
          <div class="field"><label for="date">日付<span class="req">必須</span></label>
            <input class="input" type="date" id="date" value="${state.date}"></div>
          ${
            isTransfer
              ? `<div class="field"><label for="asset">出金元<span class="req">必須</span></label><select class="input" id="asset">${assetOptions(state.asset)}</select></div>
                 <div class="field"><label for="to">入金先<span class="req">必須</span></label><select class="input" id="to">${assetOptions(state.to)}</select></div>
                 <div class="field"><label for="amount">金額<span class="req">必須</span></label>
                   <div class="with-btn"><input class="input amount" id="amount" inputmode="numeric" value="${state.amount}" placeholder="0">
                   <button class="icon-btn" type="button" data-calc="amount" aria-label="電卓">${ICON.calc}</button></div></div>`
              : `<div class="field"><label for="asset">資産<span class="req">必須</span></label><select class="input" id="asset">${assetOptions(state.asset)}</select></div>`
          }
          <div class="field"><label for="desc">内容</label>
            <div class="suggest"><input class="input" id="desc" value="${esc(state.desc)}" autocomplete="off" placeholder="例：スーパー"><ul id="sug" hidden></ul></div></div>
          ${
            isTransfer
              ? ""
              : `<div class="field"><span class="label">金額の入力</span>
                  <div><span class="seg">${[["incl", "税込"], ["excl", "税抜"]]
                    .map(([k, l]) => `<button type="button" data-input="${k}" aria-pressed="${k === state.input}">${l}</button>`)
                    .join("")}</span></div></div>
                ${state.lines
                  .map(
                    (l, i) => `<div class="line" data-line="${i}">
                      <div class="line-head"><span>内訳${i + 1}</span>${i > 0 ? `<button class="icon-btn" type="button" data-remove="${i}" aria-label="内訳${i + 1}を削除">${ICON.close}</button>` : '<span style="height:44px"></span>'}</div>
                      <div class="field"><label for="cat${i}">分類</label><select class="input" id="cat${i}" data-cat="${i}">${catOptions(l.cat)}</select>
                        ${state.showErrors && !l.cat ? '<div class="field-error">分類を入力してください。</div>' : ""}</div>
                      <div class="field"><label for="rate${i}">税率</label><select class="input" id="rate${i}" data-rate="${i}">${rateOptions(l.rate)}</select></div>
                      <div class="field"><label for="amt${i}">金額</label>
                        <div class="with-btn"><input class="input amount" id="amt${i}" data-amt="${i}" inputmode="numeric" value="${Number.isFinite(l.amt) ? l.amt : ""}" placeholder="0">
                        <button class="icon-btn" type="button" data-calc="${i}" aria-label="電卓">${ICON.calc}</button></div>
                        ${state.showErrors && !Number.isFinite(l.amt) ? '<div class="field-error">金額を入力してください。</div>' : ""}</div>
                    </div>`,
                  )
                  .join("")}
                <button type="button" class="btn add-line" id="add-line">＋ 内訳を追加</button>
                <div class="section" id="tax">${taxTable()}</div>`
          }
          <div class="field" style="margin-top:8px"><label for="memo">メモ</label><input class="input" id="memo" value="${esc(state.memo)}"></div>
          ${
            state.kind === "expense"
              ? '<p class="muted" style="font-size:12px;padding:0 12px">返品・払い戻しは、金額をマイナスで入力します。</p>'
              : ""
          }
          ${
            mode === "edit"
              ? `<div class="btn-row"><button type="button" class="btn danger" id="delete">削除</button><span class="spacer"></span><button type="button" class="btn" id="copy">コピー</button></div>`
              : ""
          }
        </form>`;
    };

    const updateTax = () => {
      const el = $("#tax");
      if (el) el.innerHTML = taxTable();
    };

    main.addEventListener("input", (e) => {
      dirty = true;
      const t = e.target;
      if (t.dataset.amt !== undefined) {
        state.lines[t.dataset.amt].amt = t.value === "" || t.value === "-" ? NaN : Number(t.value.replace(/,/g, ""));
        updateTax();
      }
      if (t.id === "amount") state.amount = t.value;
      if (t.id === "memo") state.memo = t.value;
      if (t.id === "date") state.date = t.value;
      if (t.id === "desc") {
        state.desc = t.value;
        // 内容の候補（F-TX-05）：入力した文字で始まる過去の内容
        const q = t.value.trim();
        const sug = $("#sug");
        const seen = new Set();
        const hits = [...P.tx]
          .sort((a, b) => (a.date < b.date ? 1 : -1))
          .filter((x) => x.kind === state.kind && q && x.desc.startsWith(q) && !seen.has(x.desc) && seen.add(x.desc))
          .slice(0, 10);
        sug.innerHTML = hits
          .map((x) => `<li data-sug="${x.id}">${esc(x.desc)}<small>${esc(catLabel(x.lines[0].cat))}・${yen(amountOf(x))}</small></li>`)
          .join("");
        sug.hidden = !hits.length;
      }
    });

    main.addEventListener("change", (e) => {
      const t = e.target;
      if (t.dataset.cat !== undefined) {
        const l = state.lines[t.dataset.cat];
        l.cat = Number(t.value) || null;
        // 分類を選ぶと、その分類の既定の税率にする（BR-78）
        if (l.cat) l.rate = cat(l.cat).rate;
        render();
      }
      if (t.dataset.rate !== undefined) {
        state.lines[t.dataset.rate].rate = Number(t.value);
        updateTax();
      }
      if (t.id === "asset") state.asset = Number(t.value);
      if (t.id === "to") state.to = Number(t.value);
    });

    main.addEventListener("click", async (e) => {
      const t = e.target;
      const kind = t.closest("[data-kind]");
      if (kind && kind.dataset.kind !== state.kind) {
        const wasTransfer = state.kind === "transfer";
        state.kind = kind.dataset.kind;
        // 収入と支出では分類が違うため、分類を空に戻す（画面設計書 4.2）
        state.lines = state.lines.map((l) => ({ ...l, cat: null }));
        if (wasTransfer && state.amount) state.lines = [{ cat: null, rate: 10, amt: Number(state.amount) }];
        render();
        return;
      }
      const inp = t.closest("[data-input]");
      if (inp) {
        state.input = inp.dataset.input;
        render();
        return;
      }
      const sug = t.closest("[data-sug]");
      if (sug) {
        // 候補を選ぶと、最後に登録した明細の資産・分類・税率・金額を入れる。入力済みの金額は上書きしない
        const x = txById(Number(sug.dataset.sug));
        state.desc = x.desc;
        state.asset = x.asset;
        const l0 = state.lines[0];
        l0.cat = x.lines[0].cat;
        l0.rate = x.lines[0].rate;
        if (!Number.isFinite(l0.amt)) l0.amt = x.lines[0].amt;
        render();
        return;
      }
      if (t.closest("#add-line")) {
        if (state.lines.length >= 20) return;
        state.lines.push({ cat: null, rate: 10, amt: NaN });
        render();
        return;
      }
      const rm = t.closest("[data-remove]");
      if (rm) {
        state.lines.splice(Number(rm.dataset.remove), 1);
        render();
        return;
      }
      const c = t.closest("[data-calc]");
      if (c) {
        const target = c.dataset.calc === "amount" ? $("#amount") : $(`#amt${c.dataset.calc}`);
        const v = await calculator(target.value);
        if (v !== null) {
          target.value = v;
          target.dispatchEvent(new Event("input", { bubbles: true }));
        }
        return;
      }
      if (t.closest("#close")) {
        if (!dirty || (await confirmDialog("入力中の内容を破棄しますか？", "破棄する", "入力を続ける"))) close();
        return;
      }
      if (t.closest("#delete")) {
        const x = src;
        if (await confirmDialog(`「${md(x.date)} ${x.desc} ${yen(amountOf(x))}」を削除しますか？この操作は取り消せません。`, "削除する")) close("削除しました");
        return;
      }
      if (t.closest("#copy")) {
        location.href = `transaction.html?${embed ? "embed=1&" : ""}copy=${editId}`;
        return;
      }
      if (t.closest("#save")) {
        // 入力のチェック（実装ではサーバーで行う）
        if (state.kind !== "transfer" && state.lines.some((l) => !l.cat || !Number.isFinite(l.amt))) {
          state.showErrors = true;
          render();
          $("#form-error").innerHTML = '<p class="expense" style="margin:8px 12px;font-size:13px">入力に誤りがあります。赤字の項目を確かめてください。</p>';
          return;
        }
        if (state.kind === "transfer" && state.asset === state.to) {
          $("#form-error").innerHTML = '<p class="expense" style="margin:8px 12px;font-size:13px">出金元と入金先には、別の資産を選んでください。</p>';
          return;
        }
        close(mode === "edit" ? "保存しました" : "登録しました");
      }
    });

    render();
  };

  // ---------------------------------------------------------------- 電卓（F-TX-06）
  const calculator = (initial) =>
    new Promise((resolve) => {
      const d = document.createElement("dialog");
      d.className = "calc";
      let expr = String(initial || "").replace(/,/g, "");
      const evalExpr = (s) => {
        const safe = s.replace(/×/g, "*").replace(/÷/g, "/").replace(/−/g, "-");
        if (!/^[\d+\-*/. ]*$/.test(safe) || !safe) return null;
        try {
          // 数字と演算子だけに限った式を計算する（プロトタイプ用）
          const v = Function(`"use strict";return (${safe})`)();
          return Number.isFinite(v) ? Math.trunc(v) : null; // 小数点以下は切り捨て（画面設計書 4.2）
        } catch (e) {
          return null;
        }
      };
      const draw = () => {
        const v = evalExpr(expr);
        d.querySelector(".expr").textContent = expr || " ";
        d.querySelector(".result").textContent = v === null ? "0" : v.toLocaleString("ja-JP");
      };
      const keys = ["C", "←", "÷", "×", "7", "8", "9", "−", "4", "5", "6", "+", "1", "2", "3", "=", "00", "0"];
      d.innerHTML = `<div class="expr"></div><div class="result num">0</div><div class="keys">
        ${keys.map((k) => `<button type="button" class="${/[÷×−+=C←]/.test(k) ? "op" : ""}" data-k="${k}">${k}</button>`).join("")}
        <button type="button" class="ok" data-k="ok">決定</button></div>`;
      document.body.append(d);
      d.addEventListener("click", (e) => {
        const k = e.target.closest("[data-k]")?.dataset.k;
        if (!k) return;
        if (k === "C") expr = "";
        else if (k === "←") expr = expr.slice(0, -1);
        else if (k === "=") {
          const v = evalExpr(expr);
          expr = v === null ? "" : String(v);
        } else if (k === "ok") {
          const v = evalExpr(expr);
          d.close();
          d.remove();
          resolve(v);
          return;
        } else expr += k;
        draw();
      });
      d.addEventListener("cancel", () => {
        d.remove();
        resolve(null);
      });
      draw();
      d.showModal();
    });

  // ================================================================ SC-03 検索
  const pageSearch = () => {
    renderNav("ledger");
    const main = $("#main");
    const catOpts = P.categories
      .filter((c) => !c.parent)
      .map((c) => `<option value="${c.id}">${c.kind === "income" ? "収入：" : "支出："}${esc(c.name)}</option>`)
      .join("");
    main.innerHTML = `
      <header class="header"><a class="icon-btn" href="ledger.html" aria-label="戻る">${ICON.prev}</a><h1>明細の検索</h1><span class="header-spacer"></span></header>
      <form class="form" id="f" onsubmit="return false" style="padding-bottom:0">
        <div class="field"><label for="q">キーワード</label><input class="input" id="q" placeholder="内容・メモ"></div>
        <div class="field"><label for="k">種類</label><select class="input" id="k"><option value="">すべて</option><option value="income">収入</option><option value="expense">支出</option><option value="transfer">振替</option></select></div>
        <div class="field"><label for="c">分類</label><select class="input" id="c"><option value="">すべて</option>${catOpts}</select></div>
        <div class="field"><label for="a">資産</label><select class="input" id="a"><option value="">すべて</option>${P.assets.map((a) => `<option value="${a.id}">${esc(a.name)}</option>`).join("")}</select></div>
        <div class="field"><span class="label">金額</span><div class="range"><input class="input" id="min" inputmode="numeric" placeholder="下限"><span class="muted">〜</span><input class="input" id="max" inputmode="numeric" placeholder="上限"></div></div>
        <div class="field"><span class="label">期間</span><div class="range dates"><input class="input" type="date" id="from" value="2025-10-16"><span class="muted">〜</span><input class="input" type="date" id="until" value="${P.TODAY}"></div></div>
        <div class="btn-row"><button class="btn primary block" id="go">検索</button></div>
      </form>
      <div id="res"></div>`;
    const run = () => {
      const q = $("#q").value.trim();
      const k = $("#k").value;
      const c = Number($("#c").value) || null;
      const a = Number($("#a").value) || null;
      const min = $("#min").value === "" ? null : Number($("#min").value);
      const max = $("#max").value === "" ? null : Number($("#max").value);
      const from = $("#from").value;
      const until = $("#until").value;
      const hits = P.tx.filter(
        (t) =>
          (!q || t.desc.includes(q) || t.memo.includes(q)) &&
          (!k || t.kind === k) &&
          (!c || (t.lines && t.lines.some((l) => topCat(l.cat) === c))) &&
          (!a || t.asset === a || t.to === a) &&
          (min === null || amountOf(t) >= min) &&
          (max === null || amountOf(t) <= max) &&
          t.date >= from &&
          t.date <= until,
      );
      const s = totals(hits);
      $("#res").innerHTML = hits.length
        ? `<div class="result-head"><span>${hits.length}件</span><span>収入 <span class="income num">${yen(s.income)}</span></span><span>支出 <span class="expense num">${yen(s.expense)}</span></span></div>${dayGroups(hits)}`
        : '<div class="empty">条件に合う明細はありません。</div>';
    };
    $("#go").addEventListener("click", run);
    bindRows(main);
    run();
  };

  // ================================================================ SC-04 統計
  const PALETTE = ["#4cc2b0", "#5aa9ff", "#f6b04d", "#b58cff", "#ff8fa3", "#7fd46b", "#f47c4c", "#57c7e3", "#8a94a3"];

  const pageStats = () => {
    renderNav("stats");
    const main = $("#main");
    let kind = params.get("kind") || "expense";
    let unit = "month";
    const month = "2026-10";
    let chart;

    const render = () => {
      const list = txIn(month);
      const s = totals(list);
      // 大分類ごとに内訳の税込額を集計（DB 設計書 5.4）
      const byCat = new Map();
      const lines = [];
      list.filter((t) => t.kind === kind).forEach((t) => t.lines.forEach((l) => lines.push(l)));
      lines.forEach((l) => byCat.set(topCat(l.cat), (byCat.get(topCat(l.cat)) || 0) + l.amt));
      const rows = [...byCat.entries()].sort((a, b) => b[1] - a[1]);
      const sum = rows.reduce((x, r) => x + r[1], 0);

      // 消費税（F-ST-06）：内訳ごとの税額を税率ごとに合計
      const taxByRate = new Map();
      list.filter((t) => t.kind === kind).forEach((t) => {
        const r = calcTax(t.lines, "incl");
        t.lines.forEach((l, i) => {
          const p = r.perLine[i];
          const cur = taxByRate.get(l.rate) || { excl: 0, tax: 0 };
          taxByRate.set(l.rate, { excl: cur.excl + p.excl, tax: cur.tax + p.tax });
        });
      });
      const taxRows = [...taxByRate.entries()].sort((a, b) => a[0] - b[0]);
      const taxTotal = taxRows.reduce((x, [, v]) => ({ excl: x.excl + v.excl, tax: x.tax + v.tax }), { excl: 0, tax: 0 });

      // 予算（DB 設計書 5.5）
      const budgetHtml = P.budgets
        .map((b) => {
          const used = b.cat === null ? s.expense : byCat.get(b.cat) || 0;
          const pct = Math.round((used / b.amount) * 100);
          const over = used > b.amount;
          return `<div class="budget${over ? " over" : ""}">
            <div class="top"><span>${b.cat === null ? "全体" : esc(cat(b.cat).name)}</span><span class="num">${yen(used)} / ${yen(b.amount)}</span></div>
            <div class="bar"><span style="width:${Math.min(pct, 100)}%"></span></div>
            <div class="bottom"><span>${pct}%</span><span class="num${over ? " expense" : ""}">${over ? `超過 ${yen(used - b.amount)}` : `残り ${yen(b.amount - used)}`}</span></div>
          </div>`;
        })
        .join("");

      main.innerHTML = `
        <header class="header">
          <button class="icon-btn" aria-label="前へ">${ICON.prev}</button>
          <div class="period"><span class="label">${unit === "month" ? ym(month) : "2026年"}</span></div>
          <button class="icon-btn" aria-label="次へ">${ICON.next}</button>
          <span class="seg">${[["month", "月"], ["year", "年"]].map(([k, l]) => `<button data-unit="${k}" aria-pressed="${k === unit}">${l}</button>`).join("")}</span>
        </header>
        <nav class="tabs" role="tablist">
          <button role="tab" data-kind="expense" aria-selected="${kind === "expense"}">支出 <span class="num expense" style="margin-left:6px">${yen(s.expense)}</span></button>
          <button role="tab" data-kind="income" aria-selected="${kind === "income"}">収入 <span class="num income" style="margin-left:6px">${yen(s.income)}</span></button>
        </nav>
        <div class="stats-layout">
          <div class="chart-wrap"><canvas id="pie" aria-label="分類別の割合"></canvas></div>
          <div>${rows
            .map(([id, v], i) => {
              const kids = P.categories.filter((c) => c.parent === id);
              const kidRows = kids
                .map((k) => [k.name, lines.filter((l) => l.cat === k.id).reduce((x, l) => x + l.amt, 0)])
                .filter(([, v2]) => v2);
              const self = lines.filter((l) => l.cat === id).reduce((x, l) => x + l.amt, 0);
              return `<div class="cat-row" data-open="${id}" aria-expanded="false">
                  <span class="dot" style="background:${PALETTE[Math.min(i, 8)]}"></span><span>${esc(cat(id).name)}</span>
                  <span class="pct">${Math.round((v / sum) * 100)}%</span><span class="num">${yen(v)}</span><span class="chev">›</span>
                </div>
                <div class="subcats" id="sub${id}" hidden>
                  ${kidRows.map(([n, v2]) => `<div class="cat-row"><span></span><span>└ ${esc(n)}</span><span class="num">${yen(v2)}</span></div>`).join("")}
                  <div class="cat-row"><span></span><span>└ 小分類なし</span><span class="num">${yen(self)}</span></div>
                  <a class="more" href="trends.html?type=category&id=${id}">${esc(cat(id).name)}の推移を見る ›</a>
                </div>`;
            })
            .join("")}</div>
        </div>
        ${
          kind === "expense" && unit === "month"
            ? `<section class="section"><h2>予算</h2>${budgetHtml}<a class="btn ghost" href="settings.html" style="padding:0">予算を設定する ›</a></section>`
            : ""
        }
        <section class="section"><h2>消費税</h2>
          <table class="tax-table num"><thead><tr><th>税率</th><th>税抜</th><th>消費税</th></tr></thead><tbody>
          ${taxRows.map(([r, v]) => `<tr><td>${r}%</td><td>${plain(v.excl)}</td><td>${plain(v.tax)}</td></tr>`).join("")}
          <tr class="total"><td>合計</td><td>${plain(taxTotal.excl)}</td><td>${plain(taxTotal.tax)}</td></tr></tbody></table>
        </section>
        ${unit === "year" ? '<div class="proto-note">プロトタイプ：年の集計も 10月のデータで表示しています。</div>' : ""}`;

      if (chart) chart.destroy();
      const top = rows.slice(0, 8);
      const rest = rows.slice(8).reduce((x, r) => x + r[1], 0);
      const css = getComputedStyle(document.documentElement);
      chart = new Chart($("#pie"), {
        type: "doughnut",
        data: {
          labels: [...top.map(([id]) => cat(id).name), ...(rest ? ["その他"] : [])],
          datasets: [{ data: [...top.map((r) => r[1]), ...(rest ? [rest] : [])], backgroundColor: PALETTE, borderColor: css.getPropertyValue("--surface"), borderWidth: 2 }],
        },
        options: { cutout: "58%", plugins: { legend: { display: false } }, animation: { duration: 300 } },
      });
    };

    main.addEventListener("click", (e) => {
      const k = e.target.closest("[data-kind]");
      if (k) {
        kind = k.dataset.kind;
        render();
        return;
      }
      const u = e.target.closest("[data-unit]");
      if (u) {
        unit = u.dataset.unit;
        render();
        return;
      }
      const o = e.target.closest("[data-open]");
      if (o) {
        const sub = $(`#sub${o.dataset.open}`);
        sub.hidden = !sub.hidden;
        o.setAttribute("aria-expanded", String(!sub.hidden));
      }
    });
    render();
  };

  // ================================================================ SC-05 推移グラフ
  const pageTrends = () => {
    const type = params.get("type") || "category";
    renderNav(type === "category" ? "stats" : "assets");
    const main = $("#main");
    const css = getComputedStyle(document.documentElement);
    const grid = css.getPropertyValue("--border");
    const text = css.getPropertyValue("--text-muted");
    const labels = [...P.history.months, "2026-10"].map((m) => `${Number(m.slice(5))}月`);
    const baseOpts = {
      maintainAspectRatio: false,
      plugins: { legend: { labels: { color: text } } },
      scales: {
        x: { grid: { color: grid }, ticks: { color: text } },
        y: { grid: { color: grid }, ticks: { color: text, callback: (v) => `${v / 10000}万` } },
      },
    };

    if (type === "category") {
      const id = Number(params.get("id")) || 1;
      const oct = txIn("2026-10")
        .filter((t) => t.kind === "expense")
        .flatMap((t) => t.lines)
        .filter((l) => topCat(l.cat) === id)
        .reduce((x, l) => x + l.amt, 0);
      const vals = [...P.history.food, oct];
      const avg = Math.round(vals.reduce((a, b) => a + b, 0) / vals.length);
      main.innerHTML = `
        <header class="header"><a class="icon-btn" href="stats.html" aria-label="戻る">${ICON.prev}</a><h1>${esc(cat(id).name)}の推移</h1><span class="header-spacer"></span></header>
        <div class="section" style="margin-top:0;display:flex;align-items:center;justify-content:space-between">
          <button class="icon-btn" aria-label="前へ">${ICON.prev}</button><span>2025年11月〜2026年10月</span><button class="icon-btn" aria-label="次へ">${ICON.next}</button></div>
        <div class="section"><div class="chart-wrap wide"><canvas id="c"></canvas></div></div>
        <div class="section"><div class="bill"><span>平均</span><span class="num">${yen(avg)}</span></div><div class="bill"><span>最大</span><span class="num">${yen(Math.max(...vals))}</span></div></div>
        <div class="section">${[...vals].reverse().map((v, i) => `<div class="bill"><span>${[...labels].reverse()[i]}</span><span class="num">${yen(v)}</span></div>`).join("")}</div>
        <div class="proto-note">プロトタイプ：9月以前はダミーの値です。</div>`;
      new Chart($("#c"), {
        type: "bar",
        data: { labels, datasets: [{ label: cat(id).name, data: vals, backgroundColor: PALETTE[0], borderRadius: 4 }] },
        options: { ...baseOpts, plugins: { legend: { display: false } } },
      });
    } else {
      const liabNow = -P.assets.filter((a) => a.card).reduce((x, a) => x + balance(a.id), 0);
      const assetsNow = P.assets.filter((a) => !a.card).reduce((x, a) => x + balance(a.id), 0);
      const A = [...P.history.assets, assetsNow];
      const L = [...P.history.liabilities, liabNow];
      const N = A.map((v, i) => v - L[i]);
      main.innerHTML = `
        <header class="header"><a class="icon-btn" href="assets.html" aria-label="戻る">${ICON.prev}</a><h1>資産の推移</h1><span class="header-spacer"></span></header>
        <div class="section" style="margin-top:0"><select class="input"><option>全体</option>${P.assets.map((a) => `<option>${esc(a.name)}</option>`).join("")}</select></div>
        <div class="section" style="display:flex;align-items:center;justify-content:space-between">
          <button class="icon-btn" aria-label="前へ">${ICON.prev}</button><span>2025年11月〜2026年10月</span><button class="icon-btn" aria-label="次へ">${ICON.next}</button></div>
        <div class="section"><div class="chart-wrap wide"><canvas id="c"></canvas></div></div>
        <div class="section">${labels
          .map((l, i) => ({ l, i }))
          .reverse()
          .slice(0, 4)
          .map(({ l, i }) => `<div class="bill"><span>${l}末</span><span class="num">資産 ${yen(A[i])}　負債 ${yen(L[i])}　純資産 ${yen(N[i])}</span></div>`)
          .join("")}</div>
        <div class="proto-note">プロトタイプ：資産の選択は見た目だけです。9月以前はダミーの値です。</div>`;
      const line = (label, data, color) => ({ label, data, borderColor: color, backgroundColor: color, tension: 0.25, pointRadius: 2 });
      new Chart($("#c"), {
        type: "line",
        data: {
          labels,
          datasets: [
            line("資産", A, css.getPropertyValue("--income")),
            line("負債", L, css.getPropertyValue("--expense")),
            line("純資産", N, css.getPropertyValue("--accent")),
          ],
        },
        options: baseOpts,
      });
    }
  };

  // ================================================================ SC-06 資産
  // カードの引き落とし予定（DB 設計書 5.7）。プロトタイプでは 9月分を開始残高で表している
  const cardBills = (a) => {
    const octUse = P.tx
      .filter((t) => t.asset === a.id && t.date.startsWith("2026-10"))
      .reduce((x, t) => x + (t.kind === "expense" ? amountOf(t) : t.kind === "income" ? -amountOf(t) : 0), 0);
    return [
      { date: "2026-10-27", closing: "9/30 締め", amount: -a.opening, estimate: false },
      { date: "2026-11-27", closing: "10/31 締め", amount: octUse, estimate: true },
    ];
  };

  const pageAssets = () => {
    renderNav("assets");
    const main = $("#main");
    let showHidden = false;
    const render = () => {
      const assetsSum = P.assets.filter((a) => !a.card).reduce((x, a) => x + balance(a.id), 0);
      const liab = -P.assets.filter((a) => a.card).reduce((x, a) => x + balance(a.id), 0);
      main.innerHTML = `
        <header class="header"><h1 class="left-title">資産</h1><a class="icon-btn" href="trends.html?type=assets" aria-label="資産の推移">${ICON.trend}</a></header>
        <div class="summary3">
          <div><div class="cap">資産</div><div class="val num income">${yen(assetsSum)}</div></div>
          <div><div class="cap">負債</div><div class="val num expense">${yen(liab)}</div></div>
          <div><div class="cap">純資産</div><div class="val num">${yen(assetsSum - liab)}</div></div>
        </div>
        ${P.assetGroups
          .map((g) => {
            const list = P.assets.filter((a) => a.group === g && (showHidden || !a.hidden));
            if (!list.length) return "";
            const sub = P.assets.filter((a) => a.group === g).reduce((x, a) => x + balance(a.id), 0);
            return `<div class="group-head"><span>${esc(g)}</span><span class="num">${yen(sub)}</span></div>
              ${list
                .map((a) => {
                  const b = balance(a.id);
                  const bill = a.card ? cardBills(a)[0] : null;
                  return `<a class="asset-row" href="asset.html?id=${a.id}">
                    <span>${esc(a.name)}${a.hidden ? '<span class="badge">非表示</span>' : ""}</span>
                    <span class="num${b < 0 ? " expense" : ""}">${yen(b)}</span>
                    ${bill ? `<span class="note">次回 ${md(bill.date)} ${yen(bill.amount)}${bill.estimate ? "（目安）" : ""}</span>` : ""}
                  </a>`;
                })
                .join("")}`;
          })
          .join("")}
        <label class="menu-list"><span class="item"><span>非表示の資産も表示</span><input type="checkbox" id="sh"${showHidden ? " checked" : ""} style="width:22px;height:22px"></span></label>`;
      $("#sh").addEventListener("change", (e) => {
        showHidden = e.target.checked;
        render();
      });
    };
    render();
  };

  // ================================================================ SC-07 資産詳細
  const pageAsset = () => {
    renderNav("assets");
    const main = $("#main");
    const a = asset(Number(params.get("id")) || 2);
    const month = "2026-10";
    const startBal = balance(a.id, "2026-09-30");
    const list = P.tx
      .filter((t) => inMonth(t, month) && (t.asset === a.id || t.to === a.id))
      .sort((x, y) => (x.date === y.date ? x.id - y.id : x.date < y.date ? -1 : 1));
    let run = startBal;
    let inSum = 0;
    let outSum = 0;
    const withBal = list.map((t) => {
      const amt = amountOf(t);
      const out = (t.kind === "expense" || t.kind === "transfer") && t.asset === a.id;
      const delta = out ? -amt : amt;
      if (delta >= 0) inSum += delta;
      else outSum += -delta;
      run += delta;
      return { t, after: run };
    });
    const bills = a.card ? cardBills(a) : [];
    main.innerHTML = `
      <header class="header"><a class="icon-btn" href="assets.html" aria-label="戻る">${ICON.prev}</a><h1>${esc(a.name)}</h1><span class="header-spacer"></span></header>
      <div class="section" style="margin-top:0;display:flex;align-items:center;justify-content:space-between">
        <button class="icon-btn" aria-label="前へ">${ICON.prev}</button><span class="period"><span class="label">${ym(month)}</span></span><button class="icon-btn" aria-label="次へ">${ICON.next}</button></div>
      ${
        a.card
          ? `<section class="section"><h2>${esc(a.closing)}締め・${esc(a.payMonth)}${esc(a.payDay)}払い（${esc(a.payFrom)}から）</h2>
              ${bills.map((b) => `<div class="bill"><span>${md(b.date)} 引き落とし <span class="muted">${b.closing}</span></span><span class="num">${yen(b.amount)}${b.estimate ? "（目安）" : ""}</span></div>`).join("")}</section>`
          : ""
      }
      <div class="summary3" style="grid-template-columns:repeat(4,1fr);margin-top:8px">
        <div><div class="cap">月初</div><div class="val num" style="font-size:14px">${plain(startBal)}</div></div>
        <div><div class="cap">入金</div><div class="val num income" style="font-size:14px">+${plain(inSum)}</div></div>
        <div><div class="cap">出金</div><div class="val num expense" style="font-size:14px">−${plain(outSum)}</div></div>
        <div><div class="cap">月末</div><div class="val num" style="font-size:14px">${plain(run)}</div></div>
      </div>
      ${
        withBal.length
          ? `<section class="day">${[...withBal].reverse().map(({ t, after }) => txRow(t, { assetId: a.id, after }).replace('<div class="cat">', `<div class="cat"><span class="muted">${md(t.date)}</span> `)).join("")}</section>`
          : '<div class="empty">この期間の明細はありません。</div>'
      }`;
    bindRows(main);
  };

  // ================================================================ SC-08 設定
  const pageSettings = () => {
    renderNav("settings");
    const main = $("#main");
    let theme = "dark";
    try {
      theme = localStorage.getItem("proto-theme") || "dark";
    } catch (e) {
      /* 既定のまま */
    }
    main.innerHTML = `
      <header class="header"><h1 class="left-title">設定</h1></header>
      <div class="menu-list menu-group">
        <a href="categories.html">分類</a>
        <a href="#" data-todo>資産</a>
        <a href="#" data-todo>予算</a>
        <a href="#" data-todo>定期収支</a>
        <a href="#" data-todo>税率</a>
      </div>
      <div class="menu-list menu-group">
        <a href="#" data-todo>CSV 出力・取り込み</a>
        <a href="#" data-todo>表示設定</a>
      </div>
      <div class="menu-list menu-group">
        <div class="item"><span>テーマ（プロトタイプ用の切り替え）</span>
          <span class="seg">${[["dark", "ダーク"], ["light", "ライト"], ["system", "端末"]].map(([k, l]) => `<button data-theme="${k}" aria-pressed="${k === theme}">${l}</button>`).join("")}</span></div>
      </div>
      <div class="proto-note">プロトタイプ：分類以外の設定画面は作っていません（SC-09 と同じ作りのため）。</div>`;
    main.addEventListener("click", (e) => {
      if (e.target.closest("[data-todo]")) {
        e.preventDefault();
        toast("プロトタイプでは作っていない画面です");
      }
      const t = e.target.closest("[data-theme]");
      if (t) {
        try {
          localStorage.setItem("proto-theme", t.dataset.theme);
        } catch (err) {
          /* 保存できなくても表示は切り替える */
        }
        applyTheme();
        $$("[data-theme]").forEach((b) => b.setAttribute("aria-pressed", String(b === t)));
      }
    });
  };

  // ================================================================ SC-09 分類管理
  const pageCategories = () => {
    renderNav("settings");
    const main = $("#main");
    let kind = "expense";
    const used = (id) => P.tx.filter((t) => t.lines && t.lines.some((l) => l.cat === id)).length;
    const render = () => {
      const tops = P.categories.filter((c) => c.kind === kind && !c.parent);
      const row = (c, child) => `<div class="master-row${child ? " child" : ""}${c.hidden ? " hidden" : ""}" data-id="${c.id}">
          <span class="name" data-edit="${c.id}">${esc(c.name)}</span>
          <span class="tax">${c.rate}%</span>
          <span class="moves"><button class="icon-btn" data-up="${c.id}" aria-label="上へ">${ICON.up}</button><button class="icon-btn" data-down="${c.id}" aria-label="下へ">${ICON.down}</button></span>
        </div>`;
      main.innerHTML = `
        <header class="header"><a class="icon-btn" href="settings.html" aria-label="戻る">${ICON.prev}</a><h1>分類</h1><button class="btn ghost" data-add="0">＋ 追加</button></header>
        <nav class="tabs" role="tablist">${[["expense", "支出"], ["income", "収入"]].map(([k, l]) => `<button role="tab" data-kind="${k}" aria-selected="${k === kind}">${l}</button>`).join("")}</nav>
        ${tops
          .map(
            (c) =>
              row(c, false) +
              P.categories.filter((k) => k.parent === c.id).map((k) => row(k, true)).join("") +
              `<span class="add-child" data-add="${c.id}">＋ 小分類を追加</span>`,
          )
          .join("")}
        <div class="list-caption">分類名を押すと編集できます。右の数字は既定の税率です。</div>`;
    };

    const editDialog = (c, parentId) => {
      const d = document.createElement("dialog");
      d.className = "sheet";
      const tops = P.categories.filter((x) => x.kind === kind && !x.parent && (!c || x.id !== c.id));
      const hasKids = c && P.categories.some((x) => x.parent === c.id);
      const parentVal = c ? c.parent : parentId || null;
      d.innerHTML = `<div style="height:100%;overflow:auto;background:var(--bg)">
        <header class="header"><button class="icon-btn" data-x aria-label="閉じる">${ICON.close}</button><h1>${c ? "分類の編集" : "分類の追加"}</h1><button class="btn primary" data-ok>${c ? "保存" : "登録"}</button></header>
        <div class="form">
          <div class="field"><label for="nm">名前<span class="req">必須</span></label><input class="input" id="nm" value="${c ? esc(c.name) : ""}"></div>
          <div class="field"><label for="pa">親の分類</label><select class="input" id="pa"${hasKids ? " disabled" : ""}><option value="">なし（大分類にする）</option>${tops.map((t) => `<option value="${t.id}"${t.id === parentVal ? " selected" : ""}>${esc(t.name)}</option>`).join("")}</select>
            ${hasKids ? '<div class="field-error" style="color:var(--text-muted)">小分類がある大分類は、ほかの分類の下に移動できません。</div>' : ""}</div>
          <div class="field"><label for="tx">既定の税率</label><select class="input" id="tx"><option value="">設定の既定値を使う</option>${P.taxRates.map((t) => `<option${c && c.rate === t.rate ? " selected" : ""}>${esc(t.name)}</option>`).join("")}</select></div>
          <div class="field"><span class="label">非表示</span><label><input type="checkbox"${c && c.hidden ? " checked" : ""} style="width:22px;height:22px"> 入力の選択肢に出さない</label></div>
          ${c ? '<div class="btn-row"><button class="btn danger" data-del>削除</button></div>' : ""}
        </div></div>`;
      document.body.append(d);
      d.showModal();
      d.addEventListener("click", async (e) => {
        if (e.target.closest("[data-x]")) {
          d.close();
          d.remove();
        }
        if (e.target.closest("[data-ok]")) {
          if (!$("#nm", d).value.trim()) {
            $("#nm", d).insertAdjacentHTML("afterend", '<div class="field-error">名前を入力してください。</div>');
            return;
          }
          d.close();
          d.remove();
          toast(c ? "保存しました" : "登録しました");
        }
        if (e.target.closest("[data-del]")) {
          const n = used(c.id);
          if (n) {
            toast(`「${c.name}」は${n}件の明細で使われているため削除できません。非表示にできます。`);
            return;
          }
          if (await confirmDialog(`「${c.name}」を削除しますか？この操作は取り消せません。`, "削除する")) {
            d.close();
            d.remove();
            toast("削除しました");
          }
        }
      });
    };

    main.addEventListener("click", (e) => {
      const k = e.target.closest("[data-kind]");
      if (k) {
        kind = k.dataset.kind;
        render();
        return;
      }
      const mv = e.target.closest("[data-up],[data-down]");
      if (mv) {
        // 同じ親の中で1つずつ並べ替える（画面設計書 4.9）
        const id = Number(mv.dataset.up || mv.dataset.down);
        const c = cat(id);
        const sibs = P.categories.filter((x) => x.kind === c.kind && x.parent === c.parent);
        const i = sibs.indexOf(c);
        const j = mv.dataset.up ? i - 1 : i + 1;
        if (j < 0 || j >= sibs.length) return;
        const a = P.categories.indexOf(sibs[i]);
        const b = P.categories.indexOf(sibs[j]);
        [P.categories[a], P.categories[b]] = [P.categories[b], P.categories[a]];
        render();
        return;
      }
      const ed = e.target.closest("[data-edit]");
      if (ed) {
        editDialog(cat(Number(ed.dataset.edit)));
        return;
      }
      const ad = e.target.closest("[data-add]");
      if (ad) editDialog(null, Number(ad.dataset.add) || null);
    });
    render();
  };

  // ---------------------------------------------------------------- 起動
  const pages = {
    ledger: pageLedger,
    entry: pageEntry,
    search: pageSearch,
    stats: pageStats,
    trends: pageTrends,
    assets: pageAssets,
    asset: pageAsset,
    settings: pageSettings,
    categories: pageCategories,
  };
  document.addEventListener("DOMContentLoaded", () => {
    const page = document.body.dataset.page;
    if (page !== "entry") document.body.classList.add("app");
    pages[page]();
  });
})();
