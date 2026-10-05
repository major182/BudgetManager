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
  document.body.addEventListener("htmx:confirm", (event) => {
    const question = event.detail.question;
    if (!question) return; // hx-confirm がない通信はそのまま送る
    event.preventDefault();

    const okLabel = event.detail.elt.dataset.confirmOk || "OK";
    const cancelLabel = event.detail.elt.dataset.confirmCancel || "キャンセル";
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
      if (confirmed) event.detail.issueRequest(true);
    };
    cancel.addEventListener("click", () => close(false));
    ok.addEventListener("click", () => close(true));
    dialog.addEventListener("cancel", () => dialog.remove());
    dialog.showModal();
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
  document.body.addEventListener("click", (event) => {
    if (!event.target.closest("[data-close-modal]")) return;
    const dialog = event.target.closest("dialog");
    if (dialog) dialog.close();
  });

  // ---------------------------------------------------------------- 項目の出し分け
  // data-depends-on="チェックボックスの id" を付けた項目は、チェックが入っているときだけ表示する
  // （例：クレジットカードのときだけ締め日などを出す。画面設計書 4.11）
  function applyDependsOn(root) {
    root.querySelectorAll("[data-depends-on]").forEach((el) => {
      const box = document.getElementById(el.dataset.dependsOn);
      if (!box) return;
      const update = () => {
        el.hidden = !box.checked;
      };
      box.addEventListener("change", update);
      update();
    });
  }
  document.addEventListener("DOMContentLoaded", () => applyDependsOn(document));

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
