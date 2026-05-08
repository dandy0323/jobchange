// 企業調査ダッシュボード: タブ切替・TOC自動生成・コンパクト表示切替
(function () {
  "use strict";

  document.addEventListener("DOMContentLoaded", function () {
    const tabButtons = Array.from(document.querySelectorAll(".tab-button"));
    const tabPanels = Array.from(document.querySelectorAll(".tab-panel"));
    const tocList = document.querySelector(".toc-list");
    const toggleButtons = Array.from(document.querySelectorAll(".toggle-btn"));

    // ---------------- 外部リンク セーフガード ----------------
    document.querySelectorAll('a[href^="http"]').forEach(function (a) {
      if (!a.getAttribute("target")) a.setAttribute("target", "_blank");
      if (!a.getAttribute("rel")) a.setAttribute("rel", "noopener noreferrer");
    });

    // ---------------- TOC 生成 ----------------
    function buildToc(panel) {
      if (!tocList) return;
      tocList.innerHTML = "";
      if (!panel) return;

      const headings = panel.querySelectorAll(".markdown-body h2, .markdown-body h3");
      headings.forEach(function (h) {
        if (!h.id) return;
        const li = document.createElement("li");
        li.className = h.tagName === "H3" ? "toc-h3" : "toc-h2";
        const a = document.createElement("a");
        a.href = "#" + h.id;
        // heading のテキストから絵文字バッジspanを含む HTML を使わず、テキストだけ使用
        a.textContent = h.textContent.replace(/\s+/g, " ").trim();
        a.dataset.target = h.id;
        a.addEventListener("click", function (e) {
          e.preventDefault();
          const target = document.getElementById(h.id);
          if (target) {
            target.scrollIntoView({ behavior: "smooth", block: "start" });
            history.replaceState(null, "", "#" + h.id);
          }
        });
        li.appendChild(a);
        tocList.appendChild(li);
      });

      // IntersectionObserver でアクティブ項目ハイライト
      setupScrollSpy(panel);
    }

    let activeObserver = null;
    function setupScrollSpy(panel) {
      if (activeObserver) activeObserver.disconnect();
      const headings = panel.querySelectorAll(".markdown-body h2, .markdown-body h3");
      if (!headings.length) return;

      const linkById = {};
      tocList.querySelectorAll("a").forEach(function (a) {
        linkById[a.dataset.target] = a;
      });

      activeObserver = new IntersectionObserver(
        function (entries) {
          entries.forEach(function (entry) {
            const id = entry.target.id;
            if (!id || !linkById[id]) return;
            if (entry.isIntersecting) {
              // 他の active を外し、自分を active に
              Object.values(linkById).forEach(function (a) { a.classList.remove("active"); });
              linkById[id].classList.add("active");
            }
          });
        },
        { rootMargin: "-10% 0px -70% 0px", threshold: 0 }
      );

      headings.forEach(function (h) {
        if (h.id) activeObserver.observe(h);
      });
    }

    // ---------------- タブ切替 ----------------
    function activateTab(tabId) {
      tabButtons.forEach(function (b) {
        b.classList.toggle("active", b.getAttribute("data-tab") === tabId);
      });
      let activePanel = null;
      tabPanels.forEach(function (panel) {
        const match = panel.id === "tab-" + tabId;
        panel.classList.toggle("active", match);
        if (match) activePanel = panel;
      });
      if (activePanel) buildToc(activePanel);
      window.scrollTo({ top: 0, behavior: "smooth" });
    }

    tabButtons.forEach(function (button) {
      button.addEventListener("click", function () {
        activateTab(button.getAttribute("data-tab"));
      });
    });

    // 初回ロード時は active タブの TOC を構築
    const initialPanel = document.querySelector(".tab-panel.active");
    if (initialPanel) buildToc(initialPanel);

    // ---------------- コンパクト/全文 切替 ----------------
    toggleButtons.forEach(function (btn) {
      btn.addEventListener("click", function () {
        const mode = btn.getAttribute("data-mode");
        toggleButtons.forEach(function (b) {
          b.classList.toggle("active", b === btn);
        });
        document.querySelectorAll(".markdown-body").forEach(function (body) {
          body.classList.toggle("compact", mode === "compact");
        });
      });
    });

    // ---------------- 脚注クリックでハイライト ----------------
    document.querySelectorAll(".fnref a").forEach(function (a) {
      a.addEventListener("click", function () {
        // デフォルト動作（アンカースクロール）でCSSの :target が発火
      });
    });
  });
})();
