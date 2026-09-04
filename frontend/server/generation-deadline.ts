/** Bound waiting for generation; this does not claim to cancel upstream compute. */
export async function runGenerationWithinDeadline<T>(deadline: number, operation: (remainingMs: number) => Promise<T>): Promise<T> {
  const remainingMs = deadline - Date.now()
  if (remainingMs <= 0) throw new Error('visual_generation_deadline_exceeded')
  let timer: ReturnType<typeof setTimeout> | undefined
  try {
    return await Promise.race([
      Promise.resolve().then(() => operation(remainingMs)),
      new Promise<never>((_resolve, reject) => {
        timer = setTimeout(() => reject(new Error('visual_generation_deadline_exceeded')), remainingMs)
      }),
    ])
  } finally {
    if (timer) clearTimeout(timer)
  }
}
