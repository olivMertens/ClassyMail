import { ref } from 'vue'
import i18n from '../i18n'

const t = (key, params) => i18n.global?.t?.(key, params) ?? key

const isVisible = ref(false)
const options = ref({
    title: t('dialog.message'),
    message: '',
    confirmLabel: t('dialog.ok'),
    cancelLabel: t('dialog.cancel'),
    isAlert: false, // if true, only show OK button
    isPrompt: false,
    promptValue: ''
})

let resolvePromise = null

const showDialog = ({ title, message, confirmLabel, cancelLabel, isAlert, isPrompt }) => {
    options.value = {
        title: title || t('dialog.message'),
        message: message || '',
        confirmLabel: confirmLabel || t('dialog.ok'),
        cancelLabel: cancelLabel || t('dialog.cancel'),
        isAlert: isAlert || false,
        isPrompt: isPrompt || false,
        promptValue: ''
    }
    isVisible.value = true

    return new Promise((resolve) => {
        resolvePromise = resolve
    })
}

const confirm = (message, title = t('dialog.confirmation')) => {
    return showDialog({
        title,
        message,
        confirmLabel: t('dialog.yes'),
        cancelLabel: t('dialog.no'),
        isAlert: false
    })
}

const alert = (message, title = t('dialog.alert')) => {
    return showDialog({
        title,
        message,
        confirmLabel: t('dialog.ok'),
        isAlert: true
    })
}

const prompt = (message, title = t('dialog.input')) => {
    return showDialog({
        title,
        message,
        confirmLabel: t('dialog.ok'),
        cancelLabel: t('dialog.cancel'),
        isPrompt: true
    })
}

const handleConfirm = () => {
    isVisible.value = false
    if (resolvePromise) {
        if (options.value.isPrompt) {
            resolvePromise(options.value.promptValue)
        } else {
            resolvePromise(true)
        }
    }
}

const handleCancel = () => {
    isVisible.value = false
    if (resolvePromise) {
        if (options.value.isPrompt) resolvePromise(null)
        else resolvePromise(false)
    }
}

export function useDialog() {
    return {
        isVisible,
        options,
        showDialog,
        confirm,
        alert,
        prompt,
        handleConfirm,
        handleCancel
    }
}
