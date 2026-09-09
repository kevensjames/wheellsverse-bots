// disclaim_spawn — launch the KAI desktop helper as its OWN responsible process so macOS
// consults the helper's OWN TCC grants (Screen Recording / Accessibility), not the
// grants of whatever spawned it (Terminal/python/the connector). Without this, a
// fork/exec'd child inherits the parent's TCC responsibility, so the bridge would borrow
// the connector's identity — defeating the point of a narrow signed helper.
//
// stdin/stdout/stderr are inherited by the child, so the ACP stdio protocol passes through
// transparently: caller <-> (this launcher's fds) <-> helper.
//
// build: clang -O2 -o disclaim_spawn disclaim_spawn.c
// use:   disclaim_spawn /path/to/KaiDesktopBridge.app/Contents/MacOS/KaiDesktopBridge [args...]
#include <spawn.h>
#include <stdio.h>
#include <sys/wait.h>
#include <unistd.h>

extern char **environ;
// Private SPI in libSystem; used by `open` and every CLI tool that needs its own TCC identity.
extern int responsibility_spawnattrs_setdisclaim(posix_spawnattr_t *attrs, int disclaim);

int main(int argc, char *argv[]) {
    if (argc < 2) { fprintf(stderr, "usage: %s <program> [args...]\n", argv[0]); return 2; }
    posix_spawnattr_t attr;
    posix_spawnattr_init(&attr);
    responsibility_spawnattrs_setdisclaim(&attr, 1);   // child becomes its own responsible process
    pid_t pid;
    int rc = posix_spawn(&pid, argv[1], NULL, &attr, &argv[1], environ);
    posix_spawnattr_destroy(&attr);
    if (rc != 0) { fprintf(stderr, "posix_spawn failed: %d\n", rc); return 1; }
    int status = 0;
    if (waitpid(pid, &status, 0) < 0) return 1;
    return WIFEXITED(status) ? WEXITSTATUS(status) : 1;
}
