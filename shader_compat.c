/* GLSL 1.50 compatibility; the input is an owned allocation. */
extern void *malloc(unsigned long);
extern void free(void *);

char* quadra_fix_shader_indices(char* source, unsigned long* source_length) {
    /* Generated array indices multiply by signed 1 and add signed 0.
     * GLSL 1.50 rejects this when the index is uint (NVIDIA C7011),
     * including Grass's CB3 index and material CB12 indices. Removing the
     * identity arithmetic preserves either int or uint without a cast.
     * Match the closing bracket to keep other expressions untouched. */
    static const char needle[] = " * 1 + 0]";
    static const char replacement[] = "]";
    const unsigned long needle_length = sizeof(needle) - 1;
    unsigned long matches = 0;
    for (unsigned long position = 0;
         position + needle_length <= *source_length; position++) {
        unsigned long index = 0;
        while (index < needle_length &&
               source[position + index] == needle[index])
            index++;
        if (index == needle_length) {
            matches++;
            position += needle_length - 1;
        }
    }
    if (!matches)
        return source;

    unsigned long fixed_length = *source_length - matches * (sizeof(needle) - sizeof(replacement));
    char* fixed = (char*)malloc(fixed_length + 1);
    if (!fixed)
        return source;

    unsigned long input = 0;
    unsigned long output = 0;
    while (input < *source_length) {
        unsigned long index = 0;
        while (input + index < *source_length && index < needle_length &&
               source[input + index] == needle[index])
            index++;
        if (index == needle_length) {
            for (unsigned long index = 0; index < sizeof(replacement) - 1; index++)
                fixed[output++] = replacement[index];
            input += needle_length;
        } else {
            fixed[output++] = source[input++];
        }
    }
    fixed[output] = 0;
    free(source);
    *source_length = output;
    return fixed;
}
