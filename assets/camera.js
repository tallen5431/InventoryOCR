// Make "Take a photo" buttons open the camera on mobile.
//
// dcc.Upload doesn't expose the HTML `capture` attribute, so we stamp it onto
// the inner <input type=file> of any element whose id ends in "-cam" (see
// ui_helpers.camera_upload). A MutationObserver re-applies it whenever Dash
// swaps page content or opens a modal, so it works on every page and in the
// Quick Add / material forms — no Dash callback or render-timing race needed.
(function () {
  function stampWithin(root) {
    if (!root || !root.querySelectorAll) return;
    var inputs = root.querySelectorAll('[id$="-cam"] input[type="file"]');
    for (var i = 0; i < inputs.length; i++) {
      var inp = inputs[i];
      if (inp.getAttribute('capture') !== 'environment') {
        inp.setAttribute('capture', 'environment');
      }
      if (!inp.getAttribute('accept')) {
        inp.setAttribute('accept', 'image/*');
      }
    }
  }

  function stampAll() { stampWithin(document); }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', stampAll);
  } else {
    stampAll();
  }

  try {
    var obs = new MutationObserver(function (mutations) {
      for (var m = 0; m < mutations.length; m++) {
        var added = mutations[m].addedNodes;
        for (var a = 0; a < added.length; a++) {
          if (added[a].nodeType === 1) stampWithin(added[a]);
        }
      }
    });
    obs.observe(document.documentElement, { childList: true, subtree: true });
  } catch (e) { /* MutationObserver unsupported — DOMContentLoaded pass still ran */ }
})();
