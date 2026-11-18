/* Chopper's pinned legacy decoder allocator bridge. Upstream license applies. */
#ifndef CHOPPER_LEGACY_ALLOC_H
#define CHOPPER_LEGACY_ALLOC_H
#include <stddef.h>
#include <stdlib.h>

typedef struct {
    void* (*alloc)(void*, size_t);
    void (*release)(void*, void*);
    void* opaque;
} CHOPPER_Alloc;

static void* CHOPPER_malloc(CHOPPER_Alloc memory, size_t bytes) {
    return memory.alloc ? memory.alloc(memory.opaque, bytes) : malloc(bytes);
}
static void CHOPPER_free(CHOPPER_Alloc memory, void* pointer) {
    if (!pointer) return;
    if (memory.release) memory.release(memory.opaque, pointer);
    else free(pointer);
}
#endif
