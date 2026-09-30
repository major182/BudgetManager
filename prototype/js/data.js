/*
 * プロトタイプ用のダミーデータ。
 * 実装では DB から取得する。ここでは画面の見た目を確かめるために、画面に直接データを持たせる。
 * 「今日」は 2026-10-15（木）に固定する（どの日に開いても同じ表示になるように）。
 */
window.PROTO = (function () {
  const TODAY = "2026-10-15";

  const taxRates = [
    { id: 1, name: "標準税率 10%", rate: 10 },
    { id: 2, name: "軽減税率 8%", rate: 8 },
    { id: 3, name: "非課税・対象外 0%", rate: 0 },
  ];

  // DB 設計書 7.2 の初期データ ＋ 利用者が作った小分類の例（外食）
  const categories = [
    { id: 1, kind: "expense", name: "食費", parent: null, rate: 8 },
    { id: 2, kind: "expense", name: "備品・衣類", parent: null, rate: 10 },
    { id: 3, kind: "expense", name: "交通費", parent: null, rate: 10 },
    { id: 4, kind: "expense", name: "レジャー・趣味", parent: null, rate: 10 },
    { id: 5, kind: "expense", name: "交際費", parent: null, rate: 10 },
    { id: 6, kind: "expense", name: "通信費", parent: null, rate: 10 },
    { id: 7, kind: "expense", name: "健康・医療", parent: null, rate: 0 },
    { id: 8, kind: "expense", name: "光熱費", parent: null, rate: 10 },
    { id: 9, kind: "expense", name: "保険", parent: null, rate: 0 },
    { id: 10, kind: "expense", name: "税金", parent: null, rate: 0 },
    { id: 11, kind: "expense", name: "その他", parent: null, rate: 10 },
    { id: 12, kind: "expense", name: "外食", parent: 1, rate: 10 },
    { id: 21, kind: "income", name: "給与", parent: null, rate: 0 },
    { id: 22, kind: "income", name: "賞与", parent: null, rate: 0 },
    { id: 23, kind: "income", name: "臨時収入", parent: null, rate: 0 },
    { id: 24, kind: "income", name: "利息", parent: null, rate: 0 },
    { id: 25, kind: "income", name: "その他", parent: null, rate: 0 },
  ];

  const assetGroups = ["現金", "銀行", "クレジットカード", "電子マネー"];

  const assets = [
    { id: 1, name: "現金", group: "現金", opening: 20000 },
    { id: 2, name: "〇〇銀行", group: "銀行", opening: 900000 },
    { id: 5, name: "旧口座", group: "銀行", opening: 0, hidden: true },
    {
      id: 3, name: "△△カード", group: "クレジットカード", opening: -28500, card: true,
      closing: "月末", payMonth: "翌月", payDay: "27日", payFrom: "〇〇銀行",
    },
    { id: 4, name: "Suica", group: "電子マネー", opening: 3000 },
  ];

  // 明細。lines の amt は入力した金額（すべて税込で入力した例）
  const tx = [
    { id: 1, date: "2026-10-01", kind: "expense", asset: 2, desc: "家賃", memo: "", recurring: true, lines: [{ cat: 11, rate: 0, amt: 80000 }] },
    { id: 2, date: "2026-10-02", kind: "expense", asset: 1, desc: "コンビニ", memo: "", lines: [{ cat: 1, rate: 8, amt: 540 }] },
    { id: 3, date: "2026-10-03", kind: "expense", asset: 3, desc: "ドラッグストア", memo: "", lines: [{ cat: 2, rate: 10, amt: 1320 }, { cat: 1, rate: 8, amt: 432 }] },
    { id: 4, date: "2026-10-05", kind: "expense", asset: 2, desc: "電気代", memo: "9月分", lines: [{ cat: 8, rate: 10, amt: 6820 }] },
    { id: 5, date: "2026-10-05", kind: "transfer", asset: 2, to: 1, desc: "ATM", memo: "", amount: 30000 },
    { id: 6, date: "2026-10-07", kind: "expense", asset: 4, desc: "電車", memo: "", lines: [{ cat: 3, rate: 10, amt: 420 }] },
    { id: 7, date: "2026-10-08", kind: "expense", asset: 1, desc: "ランチ", memo: "", lines: [{ cat: 12, rate: 10, amt: 1100 }] },
    { id: 8, date: "2026-10-10", kind: "expense", asset: 3, desc: "映画", memo: "", lines: [{ cat: 4, rate: 10, amt: 1900 }] },
    { id: 9, date: "2026-10-11", kind: "expense", asset: 3, desc: "スマホ代", memo: "", recurring: true, lines: [{ cat: 6, rate: 10, amt: 3980 }] },
    { id: 10, date: "2026-10-12", kind: "expense", asset: 1, desc: "スーパー", memo: "", lines: [{ cat: 1, rate: 8, amt: 2160 }, { cat: 2, rate: 10, amt: 550 }] },
    { id: 11, date: "2026-10-13", kind: "expense", asset: 3, desc: "返品", memo: "サイズ違い", lines: [{ cat: 2, rate: 10, amt: -550 }] },
    { id: 12, date: "2026-10-14", kind: "income", asset: 2, desc: "10月分", memo: "", lines: [{ cat: 21, rate: 0, amt: 250000 }] },
    { id: 13, date: "2026-10-15", kind: "expense", asset: 1, desc: "スーパー", memo: "", lines: [{ cat: 1, rate: 8, amt: 1080 }, { cat: 2, rate: 10, amt: 550 }, { cat: 2, rate: 10, amt: 330 }] },
    { id: 14, date: "2026-10-15", kind: "income", asset: 2, desc: "利息", memo: "", lines: [{ cat: 24, rate: 0, amt: 12 }] },
  ];

  // 2026年の祝日（一部）
  const holidays = {
    "2026-09-21": "敬老の日",
    "2026-09-22": "国民の休日",
    "2026-09-23": "秋分の日",
    "2026-10-12": "スポーツの日",
    "2026-11-03": "文化の日",
    "2026-11-23": "勤労感謝の日",
  };

  // 予算（DB 設計書 4.8・4.9）
  const budgets = [
    { cat: null, amount: 150000 },
    { cat: 1, amount: 30000 },
    { cat: 8, amount: 10000 },
    { cat: 6, amount: 3000 },
  ];

  // グラフ用：過去の月の集計（2025年11月〜2026年9月）。10月は明細から計算する
  const history = {
    months: ["2025-11", "2025-12", "2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09"],
    income: [250000, 520000, 250000, 250000, 250000, 250000, 250000, 480000, 250000, 250000, 250012],
    expense: [168400, 214300, 182900, 159800, 176200, 188000, 171500, 205600, 190300, 197800, 183200],
    food: [31200, 42000, 33800, 29400, 30100, 28800, 31900, 30500, 32700, 34100, 28900],
    // 9月末は 10月1日の開始時点の残高（現金 20,000 ＋ 銀行 900,000 ＋ Suica 3,000）に合わせる
    assets: [761000, 812000, 798000, 815000, 829000, 842000, 858000, 889000, 897000, 910000, 923000],
    liabilities: [21000, 38000, 26500, 19800, 24300, 30100, 22900, 35200, 27600, 31400, 28500],
  };

  return { TODAY, taxRates, categories, assetGroups, assets, tx, holidays, budgets, history };
})();
