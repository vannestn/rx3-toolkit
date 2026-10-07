/* SPDX-License-Identifier: MPL-2.0 */
#ifndef RX3_POSITION_SNAPSHOT_H
#define RX3_POSITION_SNAPSHOT_H
/* A single-attempt mailbox. Contention drops an observation, never waits.
   All access to payload uses the gate; lifecycle identity uses atomics.
   No allocation, clocks, logging, buffer access or I/O on the audio path. */
_Static_assert(__atomic_always_lock_free(sizeof(unsigned int), 0), "32-bit atomics required");
_Static_assert(__atomic_always_lock_free(sizeof(void *), 0), "pointer atomics required");
struct position_value {
    unsigned int generation, observation, frames;
    int raw;
};
struct position_slot {
    unsigned int gate, generation;
    void *reader;
    struct position_value value;
};
static int position_take(struct position_slot *s)
{
    unsigned int expected = 0;
    return __atomic_compare_exchange_n(&s->gate, &expected, 1u, 1,
                                       __ATOMIC_ACQUIRE, __ATOMIC_RELAXED);
}
static void position_release(struct position_slot *s)
{
    __atomic_store_n(&s->gate, 0u, __ATOMIC_RELEASE);
}
static void position_loading(struct position_slot *s)
{
    __atomic_store_n(&s->reader, 0, __ATOMIC_SEQ_CST);
    __atomic_add_fetch(&s->generation, 1u, __ATOMIC_SEQ_CST);
}
static void position_loaded(struct position_slot *s, void *reader)
{
    __atomic_store_n(&s->reader, reader, __ATOMIC_SEQ_CST);
}
static void position_observe(struct position_slot *s, const void *reader,
                             int raw, unsigned int frames)
{
    unsigned int generation = __atomic_load_n(&s->generation, __ATOMIC_SEQ_CST);
    if (!reader || !frames || !generation ||
        __atomic_load_n(&s->reader, __ATOMIC_SEQ_CST) != reader || !position_take(s)) return;
    if (__atomic_load_n(&s->generation, __ATOMIC_SEQ_CST) == generation &&
        __atomic_load_n(&s->reader, __ATOMIC_SEQ_CST) == reader) {
        s->value.generation = generation;
        s->value.observation++;
        s->value.raw = raw;
        s->value.frames = frames;
    }
    position_release(s);
}
static int position_read(struct position_slot *s, struct position_value *out)
{
    if (!position_take(s)) return 0;
    *out = s->value;
    position_release(s);
    return out->generation && out->generation ==
        __atomic_load_n(&s->generation, __ATOMIC_SEQ_CST) &&
        __atomic_load_n(&s->reader, __ATOMIC_SEQ_CST) != 0;
}
#endif
