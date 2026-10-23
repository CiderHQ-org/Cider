/* Real guest property regression: see run_darling_metal_budget.py. No window,
 * Roblox or account is needed. Only this process's host environment changes. */
extern int printf(const char *,...),puts(const char *);
extern unsigned alarm(unsigned);
extern void *dlsym(void *,const char *);
typedef unsigned long NSUInteger;
@interface NSObject
+ (id)new; - (void)release;
@end
@interface NSAutoreleasePool:NSObject
- (void)drain;
@end
@interface NSObject (MetalBudget)
- (NSUInteger)maxBufferLength;
- (unsigned long long)recommendedMaxWorkingSetSize;
@end
extern id MTLCreateSystemDefaultDevice(void);
struct ElfHead {void *(*open)(const char *,int);int (*close)(void *);void *(*symbol)(void *,const char *);};
#define CHECK(value) do{if(!(value)){printf("FAIL line %d: %s\n",__LINE__,#value);return 1;}}while(0)
int main(void) {
    alarm(20);
    NSAutoreleasePool *pool=[NSAutoreleasePool new];
    struct ElfHead **elf=dlsym((void *)-2,"_elfcalls");CHECK(elf && *elf);
    void *libc=(*elf)->open("libc.so.6",2);CHECK(libc);
    int (*host_setenv)(const char *,const char *,int)=(*elf)->symbol(libc,"setenv");CHECK(host_setenv);
    CHECK(!host_setenv("MACOBLOX_VRAM_BYTES","134217728",1));
    id device=MTLCreateSystemDefaultDevice();CHECK(device);
    CHECK([device maxBufferLength]>0); // populate the framework's static device facts
    unsigned long long initial=[device recommendedMaxWorkingSetSize];
    CHECK(initial==(128ULL<<20)); // require headroom so a stale value cannot pass
    CHECK(!host_setenv("MACOBLOX_VRAM_BYTES","67108864",1));
    unsigned long long reduced=[device recommendedMaxWorkingSetSize];
    CHECK(reduced==(64ULL<<20)); // the same guest device must observe the new budget
    printf("PASS: real Metal device refreshes budget from %llu to %llu bytes after its other facts are cached\n",initial,reduced);
    [device release];[pool drain];return 0;
}
