import { ref } from 'vue'

const isVisible = ref(false)
const options = ref({
    title: '',
    message: '',
    confirmLabel: 'OK',
    cancelLabel: 'Cancel',
    isAlert: false, // if true, only show OK button
    isPrompt: false,
    promptValue: ''
})

let resolvePromise = null

const showDialog = ({ title, message, confirmLabel, cancelLabel, isAlert, isPrompt }) => {
    options.value = {
        title: title || 'Message',
        message: message || '',
        confirmLabel: confirmLabel || 'OK',
        cancelLabel: cancelLabel || 'Cancel',
        isAlert: isAlert || false,
        isPrompt: isPrompt || false,
        promptValue: ''
    }
    isVisible.value = true

    return new Promise((resolve) => {
        resolvePromise = resolve
    })
}

const confirm = (message, title = 'Confirmation') => {
    return showDialog({
        title,
        message,
        confirmLabel: 'Yes',
        cancelLabel: 'No',
        isAlert: false
    })
}

const alert = (message, title = 'Alert') => {
    return showDialog({
        title,
        message,
        confirmLabel: 'OK',
        isAlert: true
    })
}

const prompt = (message, title = 'Input') => {
    return showDialog({
        title,
        message,
        confirmLabel: 'OK',
        cancelLabel: 'Cancel',
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
