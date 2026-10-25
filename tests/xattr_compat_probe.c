/* Checks xattr_compat.c inside Darling. Run it with the shim injected, on a
 * fresh file or directory of the prefix:
 *   darling shell env DYLD_INSERT_LIBRARIES=/Volumes/SystemRoot<build>/libQuadraShims.dylib \
 *       /Volumes/SystemRoot<probe> <path>
 */
extern int printf(const char *, ...);
extern int *__error(void);
extern long getxattr(const char *,const char *,void *,unsigned long,unsigned int,int);
extern int setxattr(const char *,const char *,const void *,unsigned long,unsigned int,int);
extern int removexattr(const char *,const char *,int);
int main(int argc, char **argv) {
    if (argc != 2) return 2;
    const char *name = "org.chromium.crashpad.quadra-regression";
    char b[4] = {0};
    if (getxattr(argv[1],name,b,4,0,0) != -1 || *__error() != 93) return 10;
    if (setxattr(argv[1],name,"ok",2,0,0) != 0) return 11;
    if (getxattr(argv[1],name,0,0,0,0) != 2) return 12;
    if (getxattr(argv[1],name,b,1,0,0) != -1 || *__error() != 34) return 13;
    if (getxattr(argv[1],name,b,4,0,0) != 2 || b[0]!='o' || b[1]!='k') return 14;
    if (getxattr("/quadra-nonexistent",name,b,4,0,0) != -1 || *__error()!=2) return 15;
    if (removexattr(argv[1],name,0) != 0) return 17;
    if (getxattr(argv[1],name,b,4,0,0) != -1 || *__error() != 93) return 18;
    if (removexattr(argv[1],name,0) != -1 || *__error() != 93) return 19;
    if (removexattr("/quadra-nonexistent",name,0) != -1 || *__error() != 2) return 20;
    /* Other names are passed to Darling unchanged. Its path-based setxattr
     * fails with ENOENT even for paths that exist (the bug this shim works
     * around for Crashpad), so a passed-through call fails like that; a
     * translated one would have gone through open() and succeeded. */
    if (setxattr(argv[1],"user.quadra-native","n",1,0,0) != -1 || *__error()!=2) return 16;
    printf("PASS: missing attribute, persistence, size query, short buffer, missing path, remove, passthrough\n");
    return 0;
}
