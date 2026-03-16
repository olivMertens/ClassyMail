// Placeholder for Vue 3 runtime. Download from https://unpkg.com/vue@3/dist/vue.global.prod.js
// This stub allows the app to load; replace with real Vue for production.
window.Vue = {
  createApp(options) {
    console.warn('Vue stub loaded. Please provide static/js/vue.global.prod.js');
    const app = {
      mount(selector) {
        const el = document.querySelector(selector);
        el.innerHTML = '<div style="padding:1rem;color:red;">Vue stub: please provide vue.global.prod.js in static/js.</div>';
      }
    };
    return app;
  }
};
