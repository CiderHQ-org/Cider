#include <assert.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct quadra_sparse_map { unsigned long last_index; void **data; unsigned long scan_end; };
typedef int (*insert_fn)(struct quadra_sparse_map *, int, void *);
typedef void (*foreach_fn)(struct quadra_sparse_map *, void (*)(int, void *, void *), void *);
int quadra_sparse_map_insert(struct quadra_sparse_map *, int, void *);
int quadra_sparse_map_insert_asm(struct quadra_sparse_map *, int, void *);
void quadra_sparse_map_foreach(struct quadra_sparse_map *, void (*)(int, void *, void *), void *);
void quadra_sparse_map_foreach_asm(struct quadra_sparse_map *, void (*)(int, void *, void *), void *);
struct visit { struct quadra_sparse_map *map; insert_fn insert; int indexes[32]; void *values[32]; int count, mutate; };
static void visit(int index, void *value, void *opaque) {
    struct visit *v = opaque;
    assert(v->count < 32);
    v->indexes[v->count] = index; v->values[v->count++] = value;
    if (v->mutate && index == 0) {
        v->map->data[3] = NULL; /* A callback can remove a later alias. */
        assert(!v->insert(v->map, 15, (void *)(uintptr_t)99));
    }
}
static void run(insert_fn insert, foreach_fn foreach) {
    void *slots[17] = {0};
    struct quadra_sparse_map map = {16, slots, 0};
    struct visit v = { .map=&map, .insert=insert };
    foreach(&map, visit, &v); assert(v.count == 0);
    assert(insert(&map, -1, (void *)1) == -1 && map.scan_end == 0);
    assert(insert(&map, 17, (void *)1) == -1 && map.scan_end == 0);
    assert(!insert(&map, 0, (void *)1) && map.scan_end == 1);
    assert(!insert(&map, 3, (void *)1) && map.scan_end == 4); /* dup aliases */
    assert(!insert(&map, 16, (void *)2) && map.scan_end == 17); /* inclusive len */
    foreach(&map, visit, &v);
    assert(v.count == 3 && v.indexes[0] == 0 && v.indexes[1] == 3 && v.indexes[2] == 16);
    assert(v.values[0] == v.values[1] && v.values[2] == (void *)2);
    assert(insert(&map, 16, (void *)3) == -1 && slots[16] == (void *)2);
    slots[16] = NULL; /* deletion and descriptor reuse */
    assert(!insert(&map, 16, (void *)3));
    assert(slots[16] == (void *)3 && map.scan_end == 17);
    v.count=0; v.mutate=1;
    foreach(&map, visit, &v);
    assert(v.count == 3 && v.indexes[1] == 15 && v.indexes[2] == 16);
    memset(slots, 0, sizeof(slots)); map.scan_end=0;
    assert(!insert(&map, 0, (void *)1)); v.count=0;
    foreach(&map, visit, &v);
    assert(v.count == 2 && v.indexes[0] == 0 && v.indexes[1] == 15);
    memset(slots, 0, sizeof(slots)); map.scan_end=0;
    slots[12]=(void *)5; /* Failed CAS must not advance the bound. */
    assert(insert(&map, 12, (void *)6) == -1 && map.scan_end == 0);
    slots[12]=NULL;
    map.scan_end=ULONG_MAX; v.count=0; v.mutate=0;
    foreach(&map, visit, &v); assert(v.count == 0); /* corrupt bound clamps */
    map.last_index=ULONG_MAX; map.data=NULL;
    assert(insert(&map, 0, (void *)1) == -1);
    foreach(&map, visit, &v); assert(v.count == 0); /* overflow guard */
    map.last_index=INT_MAX; map.scan_end=0;
    foreach(&map, visit, &v); assert(v.count == 0); /* no counter overflow */
    map.last_index=0; map.data=slots; map.scan_end=0;
    assert(!insert(&map, 0, (void *)7));
    foreach(&map, visit, &v); assert(v.count == 1 && v.indexes[0] == 0);
}
int main(void) {
    run(quadra_sparse_map_insert, quadra_sparse_map_foreach);
    run(quadra_sparse_map_insert_asm, quadra_sparse_map_foreach_asm);
    puts("Darling sparse map C/assembly semantics passed");
}
