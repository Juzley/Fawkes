#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/stat.h>


static inline const char *
sub_filename (const char *filename)
{
    static const char *orig = NULL;
    static const char *sub = NULL;
    const char *result;

    if (orig == NULL) {
        orig = getenv("MUTATE_ORIG_SRC");
    }

    if (sub == NULL) {
        sub = getenv("MUTATE_MODIFIED_SRC");
    }

    if (orig != NULL && sub != NULL && strcmp(orig, filename) == 0) {
        result = sub;
    } else {
        result = filename;
    }

    return result;
}


int access (const char *pathname, int mode)
{
    static int (*_access)(const char *pathname, int mode) = NULL;

    if (_access == NULL) {
        _access = dlsym(RTLD_NEXT, "access");
    }

    pathname = sub_filename(pathname);

    return _access(pathname, mode);
}


int stat (const char *pathname, struct stat *buf)
{
    static int (*_stat)(const char *pathname, struct stat *buf) = NULL;

    if (_stat == NULL) {
        _stat = dlsym(RTLD_NEXT, "stat");
    }

    pathname = sub_filename(pathname);

    return _stat(pathname, buf);
}


int open (const char *fn, int flags)
{
    static int (*_open)(const char *fn, int flags) = NULL;

    if (_open == NULL) {
        _open = dlsym(RTLD_NEXT, "open");
    }

    fn = sub_filename(fn);

    return _open(fn, flags);
}
