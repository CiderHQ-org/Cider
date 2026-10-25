/* A full notification pipe already contains a wakeup. Never block the game
 * thread waiting for a worker that might be busy in Xlib or have exited. */
#ifndef QUADRA_WORKER_WAKE_H
#define QUADRA_WORKER_WAKE_H
int quadra_wake_pipe(int descriptors[2]);
void quadra_wake_worker(int descriptor);
#endif
