const FIFTEEN_MIN = 15 * 60 * 1000;
const HOUR = 60 * 60 * 1000;

function trackState({ state, notified, probeResult, isReprobe }) {
    if (probeResult === 'unknown') {
        return { state, notified, action: 'none', intervalMs: state === 'failed' ? HOUR : FIFTEEN_MIN };
    }

    if (!isReprobe) {
        if (probeResult === 'healthy') {
            return { state: 'ok', notified: false, action: 'none', intervalMs: FIFTEEN_MIN };
        }
        return { state: 'recovering', notified, action: 'recover', intervalMs: FIFTEEN_MIN };
    }

    // isReprobe === true: this probe follows a recovery attempt
    if (probeResult === 'healthy') {
        return { state: 'ok', notified: false, action: 'notifyRecovered', intervalMs: FIFTEEN_MIN };
    }
    if (notified) {
        return { state: 'failed', notified: true, action: 'none', intervalMs: HOUR };
    }
    return { state: 'failed', notified: true, action: 'notifyFailed', intervalMs: HOUR };
}

module.exports = { trackState, FIFTEEN_MIN, HOUR };
