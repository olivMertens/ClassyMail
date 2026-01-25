module.exports = {
  env: {
    node: true,
  },
  extends: [
    'eslint:recommended',
    'plugin:vue/vue3-recommended',
  ],
  rules: {
    'vue/multi-word-component-names': 'off',
    'no-unused-vars': 'warn'
  }
}
