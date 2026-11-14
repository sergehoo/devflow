/*!
 * DevFlow — SDK « formulaire existant » : envoie un formulaire déjà présent dans
 * votre application vers DevFlow, sans backend ni API de votre côté.
 *
 *   <script src="https://VOTRE-DEVFLOW/static/support/devflow-intake.js"></script>
 *   <script>
 *     DevFlowIntake.connect(document.querySelector("#mon-formulaire"), {
 *       app: "dfp_…",                       // clé PUBLIQUE (soumission seulement), jamais un secret
 *       fields: { title: "sujet", description: "message", email: "email", name: "nom", category: "type" },
 *       onSuccess: function (r) { alert("Ticket " + r.reference); },
 *     });
 *   </script>
 * Le domaine de la page doit être autorisé dans DevFlow (Modes de collecte).
 */
(function () {
  if (window.DevFlowIntake) return;
  var script = document.currentScript, BASE = script ? new URL(script.src).origin : "";
  var FIELDS = ["title", "description", "email", "name", "category", "impact"];

  function api(key, path) { return BASE + "/api/v1/public/apps/" + encodeURIComponent(key) + "/" + path; }
  function token(key) {
    return fetch(api(key, "?mode=form"), { credentials: "omit" })
      .then(function (r) { return r.json().then(function (b) { if (!r.ok) throw new Error(b.detail || "Formulaire indisponible."); return b.form_token; }); });
  }

  function connect(form, options) {
    options = options || {};
    var key = options.app, map = options.fields || {}, pending = token(key);
    var trap = document.createElement("input");  // champ piège invisible (robots)
    trap.name = "website"; trap.tabIndex = -1; trap.autocomplete = "off"; trap.setAttribute("aria-hidden", "true");
    trap.style.cssText = "position:absolute;left:-10000px;width:1px;height:1px;opacity:0";
    form.append(trap);
    var status = document.createElement("p"); status.setAttribute("role", "status"); status.hidden = true; form.after(status);

    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var source = new FormData(form), data = new FormData();
      FIELDS.forEach(function (f) { var v = source.get(map[f] || f); if (v) data.append(f, v); });
      form.querySelectorAll("input[type=file]").forEach(function (input) {
        Array.prototype.slice.call(input.files).slice(0, 3).forEach(function (file) { data.append("attachments", file); });
      });
      data.append("website", trap.value); data.append("mode", "form"); data.append("page_url", location.origin + location.pathname);
      var submit = form.querySelector("[type=submit]"); if (submit) submit.disabled = true;
      pending.then(function (formToken) {
        data.append("form_token", formToken);
        return fetch(api(key, "tickets/"), { method: "POST", body: data, credentials: "omit" });
      }).then(function (r) {
        return r.json().then(function (body) { if (!r.ok) throw new Error(body.detail || "Envoi impossible."); return body; });
      }).then(function (result) {
        status.textContent = (result.created ? "Signalement transmis. Référence : " : "Signalement déjà reçu. Référence : ") + result.reference;
        status.hidden = false; form.reset(); if (options.onSuccess) options.onSuccess(result);
      }).catch(function (err) {
        status.textContent = err.message; status.hidden = false; if (options.onError) options.onError(err);
      }).finally(function () {
        if (submit) submit.disabled = false; pending = token(key);  // nouveau jeton pour l'envoi suivant
      });
    });
  }
  window.DevFlowIntake = { connect: connect };
})();
