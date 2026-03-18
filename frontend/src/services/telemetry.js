import { ApplicationInsights } from '@microsoft/applicationinsights-web'

const connectionString = import.meta.env.VITE_APPINSIGHTS_CONNECTION_STRING

let appInsights = null

if (connectionString) {
    appInsights = new ApplicationInsights({
        config: {
            connectionString: connectionString,
            enableAutoRouteTracking: true, // option to log all route changes
            disableAjaxTracking: false,
            autoExceptionTracking: true
        }
    })
    appInsights.loadAppInsights()
    console.log('Azure Application Insights initialized')
} else {
    console.warn('No VITE_APPINSIGHTS_CONNECTION_STRING found. Telemetry disabled.')
}

export const trackEvent = (name, properties = {}) => {
    if (appInsights) {
        appInsights.trackEvent({ name }, properties)
    }
}

export const trackException = (error, properties = {}) => {
    if (appInsights) {
        appInsights.trackException({ exception: error, properties })
    } else {
        console.error('[Telemetry Disabled] Exception:', error)
    }
}

export const trackTrace = (message, severityLevel, properties = {}) => {
    if (appInsights) {
        appInsights.trackTrace({ message, severityLevel }, properties)
    }
}

export default appInsights
