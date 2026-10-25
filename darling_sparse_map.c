/* Source for the two position-independent replacements in darling_patches.py.
 * Based on Darling libkqueue's map.c. It is not linked into the injected shim.
 *
 * Copyright (c) 2011 Mark Heily <mark@heily.com>
 * Permission to use, copy, modify, and distribute this software for any
 * purpose with or without fee is hereby granted, provided that the above
 * copyright notice and this permission notice appear in all copies.
 * THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
 * WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
 * MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
 * ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
 * WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
 * ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
 * OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
 */
typedef unsigned long sparse_size;
struct quadra_sparse_map {
    /* Darling getrlimit returns the highest valid descriptor, inclusively. */
    sparse_size last_index;
    void **data;
    sparse_size scan_end;
};
_Static_assert(sizeof(struct quadra_sparse_map) == 24, "64-bit map allocation");

int quadra_sparse_map_insert(struct quadra_sparse_map *map, int index, void *value) {
    if (index < 0 || map->last_index > 2147483647UL || (unsigned int)index > map->last_index)
        return -1;
    void *expected = 0;
    if (!__atomic_compare_exchange_n(&map->data[index], &expected, value, 0,
                                    __ATOMIC_SEQ_CST, __ATOMIC_SEQ_CST))
        return -1;
    /* Both original insertion call sites hold kq_mtx, as do map walkers.
     * Keeping the greatest successful index is sufficient after deletion. */
    sparse_size end = (unsigned int)index + 1UL;
    if (end > map->scan_end) map->scan_end = end;
    return 0;
}
void quadra_sparse_map_foreach(struct quadra_sparse_map *map,
        void (*callback)(int, void *, void *), void *context) {
    for (sparse_size index=0; ; index++) {
        if (map->last_index > 2147483647UL) return;
        sparse_size capacity = map->last_index + 1;
        sparse_size end = map->scan_end < capacity ? map->scan_end : capacity;
        if (index >= end) return;
        void *value = map->data[index];
        if (value) callback((int)index, value, context);
    }
}
