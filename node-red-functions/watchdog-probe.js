function buildProbeUrl(token) {
    return `https://api.telegram.org/bot${token}/getUpdates?timeout=0&limit=1`;
}

function evaluateProbe(statusCode) {
    if (statusCode === 409) return 'healthy';
    if (statusCode === 200) return 'dead';
    return 'unknown';
}

module.exports = { buildProbeUrl, evaluateProbe };
