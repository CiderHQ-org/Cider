#ifndef QUADRA_TELEMETRY_HOSTS_H
#define QUADRA_TELEMETRY_HOSTS_H
/* Only the known pixel beacons; never match a hostname by substring. */
static int quadra_is_blocked_telemetry(const char *node) {
    if (!node) return 0;
    char host[254];
    unsigned int length = 0;
    while (node[length]) {
        if (length == sizeof host - 1) return 0;
        char c = node[length];
        host[length++] = c >= 'A' && c <= 'Z' ? c + ('a' - 'A') : c;
    }
    if (length && host[length - 1] == '.') length--;
    host[length] = 0;
    static const char *domains[] = {"silver.roblox.com", "pulsar.roblox.com", "gold.roblox.com"};
    for (int i = 0; i < 3; i++) {
        unsigned int n = 0;
        while (domains[i][n]) n++;
        if (length < n || (length > n && host[length - n - 1] != '.')) continue;
        unsigned int j = 0;
        while (j < n && host[length - n + j] == domains[i][j]) j++;
        if (j == n) return 1;
    }
    /* Keep the existing lms-* regional latency-probe exclusion. */
    static const char suffix[] = ".roblox.com";
    if (length > 4 + sizeof suffix - 1 && host[0] == 'l' && host[1] == 'm' &&
        host[2] == 's' && host[3] == '-') {
        unsigned int i = 0;
        while (i < sizeof suffix - 1 && host[length - (sizeof suffix - 1) + i] == suffix[i]) i++;
        return i == sizeof suffix - 1;
    }
    return 0;
}
#endif
