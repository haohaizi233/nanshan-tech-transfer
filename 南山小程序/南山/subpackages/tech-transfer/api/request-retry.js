const DEFAULT_ATTEMPTS = 3
const DEFAULT_BASE_DELAY_MS = 300

function wait(ms) {
	return new Promise((resolve) => setTimeout(resolve, ms))
}

/** Retry short-lived transport failures without changing the request contract. */
export async function retryRequest(operation, {
	attempts = DEFAULT_ATTEMPTS,
	baseDelayMs = DEFAULT_BASE_DELAY_MS,
	sleep = wait,
} = {}) {
	let lastError
	for (let attempt = 1; attempt <= attempts; attempt += 1) {
		try {
			return await operation()
		} catch (error) {
			lastError = error
			if (attempt < attempts) await sleep(baseDelayMs * attempt)
		}
	}
	throw lastError
}
