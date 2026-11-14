/*!
 * DevFlow — widget « Signaler un problème » (aucune dépendance, aucun secret).
 *   <script src="https://VOTRE-DEVFLOW/static/support/devflow-widget.js"
 *           data-app="mon-app-12" data-name="Mon application" data-label="Signaler un problème" defer></script>
 * Le formulaire s'ouvre dans un iframe servi par DevFlow ; seul un domaine autorisé
 * dans DevFlow peut l'afficher (Content-Security-Policy frame-ancestors).
 */
(function () {
  var script = document.currentScript;
  if (!script || window.DevFlowWidget) return;
  var base = new URL(script.src).origin, slug = script.getAttribute("data-app") || "";
  var label = script.getAttribute("data-label") || "Signaler un problème", name = script.getAttribute("data-name") || "";
  var color = script.getAttribute("data-color") || "#ffd54a";
  if (!/^[a-z0-9-]{3,80}$/.test(slug)) { console.warn("DevFlow widget : attribut data-app invalide."); return; }
  var overlay, frame, button;

  function close() { if (overlay) { overlay.remove(); overlay = null; } if (button) button.focus(); }
  function open() {
    if (overlay) return;
    overlay = document.createElement("div");
    overlay.setAttribute("role", "dialog"); overlay.setAttribute("aria-modal", "true"); overlay.setAttribute("aria-label", label);
    overlay.style.cssText = "position:fixed;inset:0;z-index:2147483646;background:rgba(20,20,20,.35);display:flex;align-items:flex-end;justify-content:flex-end;padding:16px";
    var box = document.createElement("div");
    box.style.cssText = "position:relative;width:min(440px,100%);height:min(680px,calc(100vh - 32px));background:#fff;border-radius:22px;overflow:hidden;box-shadow:0 18px 48px rgba(0,0,0,.25)";
    var x = document.createElement("button");
    x.type = "button"; x.textContent = "×"; x.setAttribute("aria-label", "Fermer");
    x.style.cssText = "position:absolute;top:8px;right:10px;z-index:1;border:0;background:#f5f0e6;border-radius:999px;width:32px;height:32px;font:20px/1 sans-serif;cursor:pointer";
    x.addEventListener("click", close);
    var params = new URLSearchParams({ embed: "1", origin: location.origin, page: location.origin + location.pathname });
    if (name) params.set("name", name);
    frame = document.createElement("iframe");
    frame.title = label; frame.src = base + "/support/app/" + encodeURIComponent(slug) + "/?" + params.toString();
    frame.setAttribute("allow", "display-capture"); frame.style.cssText = "border:0;width:100%;height:100%";
    box.append(x, frame); overlay.append(box);
    overlay.addEventListener("click", function (e) { if (e.target === overlay) close(); });
    document.addEventListener("keydown", function esc(e) { if (e.key === "Escape") { close(); document.removeEventListener("keydown", esc); } });
    document.body.append(overlay); x.focus();
  }
  window.addEventListener("message", function (e) {
    if (e.origin !== base || !e.data || e.data.type !== "devflow:ticket") return;
    script.dispatchEvent(new CustomEvent("devflow:ticket", { detail: { reference: e.data.reference }, bubbles: true }));
  });
  function mount() {
    button = document.createElement("button");
    button.type = "button"; button.textContent = label; button.setAttribute("data-devflow-widget", "");
    button.style.cssText = "position:fixed;right:20px;bottom:20px;z-index:2147483645;border:0;border-radius:999px;padding:12px 18px;font:600 14px system-ui,sans-serif;background:" + color + ";color:#1f1f1f;box-shadow:0 8px 24px rgba(0,0,0,.18);cursor:pointer";
    button.addEventListener("click", open);
    document.body.append(button);
  }
  window.DevFlowWidget = { open: open, close: close };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount); else mount();
})();
