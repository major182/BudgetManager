/*
 * 全画面に共通する画面の動き（画面設計書 1.4・1.6）。
 * htmx で足りない小さな動きだけを、ビルドの要らない素の JavaScript で書く（技術選定書 5.3）。
 */
(function () {
  "use strict";

  // ---------------------------------------------------------------- 完了の知らせ（画面設計書 1.6）
  // 画面の上部に数秒表示して消す
  function toast(message) {
    const el = document.createElement("div");
    el.className = "toast";
    el.setAttribute("role", "status");
    el.textContent = message; // textContent なので HTML として解釈されない（S-02）
    document.body.append(el);
    setTimeout(() => el.remove(), 2500);
  }
  window.budgetToast = toast;

  // サーバーが Django の messages で返した知らせ（ページの読み込み時）
  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-toast]").forEach((el) => {
      toast(el.dataset.toast);
      el.remove();
    });
  });

  // htmx の応答の HX-Trigger ヘッダーで送られた知らせ：{"showMessage": "登録しました"}
  document.body.addEventListener("showMessage", (event) => {
    toast(event.detail.value);
  });

  // ---------------------------------------------------------------- 確認ダイアログ（画面設計書 1.6）
  // hx-confirm を付けた要素は、ブラウザ標準の confirm ではなく、この画面のダイアログで確かめる。
  // ボタンの文言は data-confirm-ok（例：削除する）で指定する（画面設計書 6.2）
  function confirmDialog(question, okLabel, cancelLabel) {
    return new Promise((resolve) => {
      const dialog = document.createElement("dialog");
    dialog.className = "confirm";
    const text = document.createElement("p");
    text.textContent = question;
    const row = document.createElement("div");
    row.className = "btn-row";
    const cancel = document.createElement("button");
    cancel.className = "btn";
    cancel.textContent = cancelLabel;
    const ok = document.createElement("button");
    ok.className = "btn danger";
    ok.textContent = okLabel;
    row.append(cancel, ok);
    dialog.append(text, row);
    document.body.append(dialog);

    const close = (confirmed) => {
      dialog.close();
      dialog.remove();
      resolve(confirmed);
    };
    cancel.addEventListener("click", () => close(false));
    ok.addEventListener("click", () => close(true));
    dialog.addEventListener("cancel", () => {
      dialog.remove();
      resolve(false);
    });
    dialog.showModal();
    });
  }

  document.body.addEventListener("htmx:confirm", (event) => {
    const question = event.detail.question;
    if (!question) return; // hx-confirm がない通信はそのまま送る
    event.preventDefault();
    const el = event.detail.elt;
    const okLabel = el.dataset.confirmOk || "OK";
    const cancelLabel = el.dataset.confirmCancel || "キャンセル";
    confirmDialog(question, okLabel, cancelLabel).then((confirmed) => {
      if (confirmed) event.detail.issueRequest(true);
    });
  });

  // ---------------------------------------------------------------- 入力の小窓（画面設計書 1.7・4.9）
  // htmx が小窓の中身（#modal-body）を入れたら小窓を開く。誤りで中身が差し替わったときは開いたまま
  document.body.addEventListener("htmx:afterSwap", (event) => {
    if (event.detail.target.id !== "modal-body") return;
    const dialog = document.getElementById("modal");
    if (dialog && !dialog.open) dialog.showModal();
    applyDependsOn(event.detail.target);
  });
  // 閉じるボタン
  document.body.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-close-modal], [data-confirm-discard]");
    if (!button) return;
    const form = button.closest("form");
    if (button.hasAttribute("data-confirm-discard") && form && form.dataset.dirty) {
      event.preventDefault();
      const ok = await confirmDialog("入力中の内容を破棄しますか？", "破棄する", "入力を続ける");
      if (!ok) return;
      if (button.href) {
        location.href = button.href;
        return;
      }
    }
    if (button.hasAttribute("data-close-modal")) {
      const dialog = button.closest("dialog");
      if (dialog) dialog.close();
    }
  });
  // 入力したら「入力中」の印を付ける。描き直したフォームにも、送った内容が残っているので印を付け直す
  document.body.addEventListener("input", (event) => {
    const form = event.target.closest("form[data-entry]");
    if (form) form.dataset.dirty = "1";
  });
  document.body.addEventListener("htmx:afterSwap", (event) => {
    if (event.detail.requestConfig.verb !== "post") return;
    const form = document.querySelector("form[data-entry]");
    if (form) form.dataset.dirty = "1";
  });

  // ---------------------------------------------------------------- 項目の出し分け
  // data-depends-on="入力欄の id" を付けた項目は、条件に合うときだけ表示する
  // - チェックボックス：チェックが入っているとき（例：クレジットカードのときだけ締め日などを出す。画面設計書 4.11）
  // - 選択欄：値が data-depends-value（空白区切り）のどれかのとき（例：毎週なら曜日を出す。画面設計書 4.13）
  function applyDependsOn(root) {
    root.querySelectorAll("[data-depends-on]").forEach((el) => {
      const box = document.getElementById(el.dataset.dependsOn);
      if (!box) return;
      const values = (el.dataset.dependsValue || "").split(" ").filter(Boolean);
      const update = () => {
        el.hidden = values.length ? !values.includes(box.value) : !box.checked;
      };
      box.addEventListener("change", update);
      update();
    });
  }
  document.addEventListener("DOMContentLoaded", () => applyDependsOn(document));

  // ---------------------------------------------------------------- 分類の既定の税率（BR-78・79）
  // 定期収支の小窓で分類を選んだら、その分類の既定の税率にする。
  // 対応表（分類の id → 税率の id）は、テンプレートが json_script（id="default-rates"）で埋め込む
  document.body.addEventListener("change", (event) => {
    if (event.target.id !== "id_category") return;
    const table = document.getElementById("default-rates");
    const rate = document.getElementById("id_tax_rate");
    if (!table || !rate) return;
    const value = JSON.parse(table.textContent)[event.target.value];
    if (value) rate.value = value;
  });

  // ---------------------------------------------------------------- 電卓（F-TX-06、画面設計書 4.2）
  // 四則演算の結果を金額の欄に入れる。結果の小数点以下は切り捨てる（金額は円の整数。BR-02）

  // 数字と + − × ÷ だけを読む小さな計算機。文字列をプログラムとして実行する eval は使わない
  function evaluate(expr) {
    const normalized = expr.replace(/×/g, "*").replace(/÷/g, "/").replace(/−/g, "-");
    const tokens = normalized.match(/\d+(\.\d+)?|[+\-*/]/g);
    if (!tokens) return null;
    let pos = 0;
    const number = () => {
      let sign = 1;
      while (tokens[pos] === "-" || tokens[pos] === "+") {
        if (tokens[pos] === "-") sign = -sign;
        pos++;
      }
      const v = Number(tokens[pos++]);
      return Number.isFinite(v) ? sign * v : NaN;
    };
    // 掛け算・割り算を先に計算する
    const term = () => {
      let v = number();
      while (tokens[pos] === "*" || tokens[pos] === "/") {
        const op = tokens[pos++];
        const r = number();
        v = op === "*" ? v * r : v / r;
      }
      return v;
    };
    let v = term();
    while (tokens[pos] === "+" || tokens[pos] === "-") {
      const op = tokens[pos++];
      const r = term();
      v = op === "+" ? v + r : v - r;
    }
    return Number.isFinite(v) && pos === tokens.length ? Math.trunc(v) : null;
  }

  function openCalculator(input) {
    const dialog = document.createElement("dialog");
    dialog.className = "calc";
    let expr = (input.value || "").replace(/,/g, "");
    const exprEl = document.createElement("div");
    exprEl.className = "expr";
    const resultEl = document.createElement("div");
    resultEl.className = "result num";
    const pad = document.createElement("div");
    pad.className = "keys";
    const keys = ["C", "←", "÷", "×", "7", "8", "9", "−", "4", "5", "6", "+", "1", "2", "3", "=", "00", "0", "決定"];
    for (const k of keys) {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = k;
      b.dataset.key = k;
      if (/[÷×−+=C←]/.test(k)) b.className = "op";
      if (k === "決定") b.className = "ok";
      pad.append(b);
    }
    dialog.append(exprEl, resultEl, pad);
    const draw = () => {
      exprEl.textContent = expr || " ";
      const v = evaluate(expr);
      resultEl.textContent = v === null ? "0" : v.toLocaleString("ja-JP");
    };
    pad.addEventListener("click", (event) => {
      const k = event.target.dataset.key;
      if (!k) return;
      if (k === "C") expr = "";
      else if (k === "←") expr = expr.slice(0, -1);
      else if (k === "=") {
        const v = evaluate(expr);
        expr = v === null ? "" : String(v);
      } else if (k === "決定") {
        const v = evaluate(expr);
        if (v !== null) {
          input.value = String(v);
          // 税額の表を計算し直させる
          input.dispatchEvent(new Event("input", { bubbles: true }));
          input.dispatchEvent(new Event("change", { bubbles: true }));
        }
        dialog.close();
        dialog.remove();
        return;
      } else expr += k;
      draw();
    });
    dialog.addEventListener("cancel", () => dialog.remove());
    document.body.append(dialog);
    draw();
    dialog.showModal();
  }

  document.body.addEventListener("click", (event) => {
    const button = event.target.closest("[data-calc]");
    if (!button) return;
    const input = document.getElementById(button.dataset.calc);
    if (input) openCalculator(input);
  });

  // ---------------------------------------------------------------- CSV の取り込みの確認（MSG-C04）
  document.body.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-confirm-csv]");
    if (!button || button.dataset.confirmed) return;
    event.preventDefault();
    if (await confirmDialog(button.dataset.confirmCsv, "取り込む", "キャンセル")) {
      button.dataset.confirmed = "1";
      button.form.requestSubmit(button);
    }
  });

  // ---------------------------------------------------------------- 通信のエラー（画面設計書 6.6）
  // サーバーのエラー（MSG-S01）
  document.body.addEventListener("htmx:responseError", (event) => {
    if (event.detail.xhr.status === 404) {
      toast("ページが見つかりません。");
    } else {
      toast("エラーが発生しました。時間をおいて、もう一度お試しください。");
    }
  });
  // 通信そのものの失敗（MSG-S03。Tailscale の接続切れなど）
  document.body.addEventListener("htmx:sendError", () => {
    toast("通信できませんでした。接続を確かめてから、もう一度お試しください。");
  });
})();
