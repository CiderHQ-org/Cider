#include <assert.h>
#include <stdio.h>
#include "../telemetry_hosts.h"
int main(void) {
    const char *blocked[] = {"gold.roblox.com", "silver.roblox.com", "PULSAR.ROBLOX.COM.",
                            "us.silver.roblox.com", "a.pulsar.roblox.com", "lms-us.roblox.com"};
    const char *allowed[] = {0, "", "roblox.com", "lms.roblox.com", "notsilver.roblox.com",
                            "gold.roblox.com.example.org", "games.roblox.com", "silver.roblox.co"};
    for (unsigned int i = 0; i < sizeof blocked / sizeof *blocked; i++)
        assert(quadra_is_blocked_telemetry(blocked[i]));
    for (unsigned int i = 0; i < sizeof allowed / sizeof *allowed; i++)
        assert(!quadra_is_blocked_telemetry(allowed[i]));
    puts("PASS: beacon names, subdomains, case, trailing dot and unrelated hosts");
}
