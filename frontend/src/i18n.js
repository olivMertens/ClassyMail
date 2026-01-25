import { createI18n } from 'vue-i18n'
import en from './locales/en.json'
import fr from './locales/fr.json'

const savedLocale = localStorage.getItem('classimail-locale') || 'en'

const i18n = createI18n({
    legacy: false, // Usage with Composition API
    locale: savedLocale,
    fallbackLocale: 'en',
    messages: {
        en,
        fr
    }
})

export default i18n
