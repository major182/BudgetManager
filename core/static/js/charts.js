/*
 * 統計・推移のグラフ（画面設計書 4.4・4.5）。Chart.js 4.5.1 で描く。
 * グラフの数値は、テンプレートの json_script（<script type="application/json">）から読む。
 * 色はテーマの CSS 変数から取り、ダーク・ライトのどちらでも見やすくする。
 */
(function () {
  "use strict";

  // 分類の色（上位 8 分類と「その他」）。app.css の .dot-0〜8 と同じ順
  const PALETTE = ["#4cc2b0", "#5aa9ff", "#f6b04d", "#b58cff", "#ff8fa3", "#7fd46b", "#f47c4c", "#57c7e3", "#8a94a3"];
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const data = (id) => JSON.parse(document.getElementById(id).textContent);
  const man = (v) => (Math.abs(v) >= 10000 ? (v / 10000).toLocaleString("ja-JP", { maximumFractionDigits: 1 }) + "万" : v.toLocaleString("ja-JP"));

  function axes() {
    const grid = css("--border");
    const text = css("--text-muted");
    return {
      x: { grid: { color: grid }, ticks: { color: text } },
      y: { grid: { color: grid }, ticks: { color: text, callback: man } },
    };
  }

  function draw() {
    const pie = document.getElementById("chart-pie");
    if (pie) {
      const d = data("pie-data");
      new Chart(pie, {
        type: "doughnut",
        data: { labels: d.labels, datasets: [{ data: d.values, backgroundColor: PALETTE, borderColor: css("--surface"), borderWidth: 2 }] },
        options: { cutout: "58%", plugins: { legend: { display: false } }, animation: { duration: 300 } },
      });
    }
    const bar = document.getElementById("chart-bar");
    if (bar) {
      const d = data("bar-data");
      new Chart(bar, {
        type: "bar",
        data: { labels: d.labels, datasets: [{ data: d.values, backgroundColor: PALETTE[0], borderRadius: 4 }] },
        options: { maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: axes() },
      });
    }
    const line = document.getElementById("chart-line");
    if (line) {
      const d = data("line-data");
      const series = (label, values, color) => ({ label, data: values, borderColor: color, backgroundColor: color, tension: 0.25, pointRadius: 2 });
      const datasets = d.balance
        ? [series("残高", d.balance, css("--accent"))]
        : [series("資産", d.assets, css("--income")), series("負債", d.liabilities, css("--expense")), series("純資産", d.net, css("--accent"))];
      new Chart(line, {
        type: "line",
        data: { labels: d.labels, datasets },
        options: { maintainAspectRatio: false, plugins: { legend: { labels: { color: css("--text-muted") } } }, scales: axes() },
      });
    }
  }
  document.addEventListener("DOMContentLoaded", draw);
})();
