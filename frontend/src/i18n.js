import { createI18n } from 'vue-i18n'
import en from './locales/en.json'
import fr from './locales/fr.json'
import es from './locales/es.json'
import de from './locales/de.json'
import it from './locales/it.json'

const savedLocale = localStorage.getItem('ClassyMail-locale') || 'en'

const i18n = createI18n({
    legacy: false, // Usage with Composition API
    locale: savedLocale,
    fallbackLocale: 'en',
    messages: {
        en,
        fr,
        es,
        de,
        it
    }
})

export default i18n
