// JS minimal, progressive enhancement uniquement — le site fonctionne sans JS.
(function () {
  "use strict";

  var toggle = document.getElementById("nav-toggle");
  var nav = document.getElementById("nav-principale");
  if (toggle && nav) {
    toggle.addEventListener("click", function () {
      var isOpen = nav.classList.toggle("is-open");
      toggle.setAttribute("aria-expanded", isOpen ? "true" : "false");
    });
  }

  // Formulaire de signalement : focus visuel sur le champ "résultat du recontact"
  // quand "Oui" est sélectionné, pour guider l'utilisateur (le champ reste
  // utilisable sans JS, la validation serveur reste la référence).
  var recontactRadios = document.querySelectorAll('input[name="recontact_attempted"]');
  var outcomeField = document.getElementById("recontact_outcome");
  if (recontactRadios.length && outcomeField) {
    var syncOutcome = function () {
      var oui = document.querySelector('input[name="recontact_attempted"]:checked');
      outcomeField.closest("fieldset") || null;
      if (oui && oui.value === "oui") {
        outcomeField.setAttribute("required", "required");
      } else {
        outcomeField.removeAttribute("required");
      }
    };
    recontactRadios.forEach(function (r) { r.addEventListener("change", syncOutcome); });
    syncOutcome();
  }
})();
