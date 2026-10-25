#ifndef QUADRA_GRAPHICS_CONTEXT_H
#define QUADRA_GRAPHICS_CONTEXT_H

/* EGL outcomes are recorded before Darling discards them in its CGL layer. */
typedef struct {
    void *previous;
    unsigned long binding_serial;
    void **surface_slot;
    void *previous_surface;
} quadra_context_change;

int quadra_begin_context_change(quadra_context_change *change);
int quadra_finish_context_change(const quadra_context_change *change, int cgl_error);
void quadra_record_egl_binding(unsigned int succeeded, void *context);
void quadra_register_egl_context(void *context);
void quadra_forget_egl_context(void *context);
int quadra_graphics_first_draw(void);
void quadra_record_egl_swap(unsigned int succeeded);
unsigned long quadra_egl_swap_serial(void);
int quadra_finish_cgl_swap(unsigned long serial, int cgl_error);
int quadra_bind_desktop_gl(void);
int quadra_egl_binding_error(void);
int quadra_capture_egl_error(void);
int quadra_graphics_get_error(void);

/* Return an owned, terminated copy, or NULL on allocation/invalid input. */
int *quadra_copy_pixel_attributes(const int *attributes);

#endif
