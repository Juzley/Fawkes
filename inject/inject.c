#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdlib.h>
#include <string.h>


int open (const char *fn, int flags)
{
    static int (*_open)(const char *fn, int flags) = NULL;
    static const char  *orig = NULL;
    static const char  *sub = NULL;

    if (_open == NULL) {
        _open = dlsym(RTLD_NEXT, "open");
    }

    if (orig == NULL) {
        orig = getenv("MUTATE_ORIG_SRC");
    }

    if (sub == NULL) {
        sub = getenv("MUTATE_MODIFIED_SRC");
    }

    if (orig != NULL && sub != NULL && strcmp(orig, fn) == 0) {
        fn = sub;
    }

    return _open(fn, flags);
}
