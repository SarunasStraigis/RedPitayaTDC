// Lifecycle shim: nginx loads this as controllerhf.so.
// Start/Stop is control.sh (via /pitaya_tdc/control/). Opening or leaving
// the tile must not load, unload, or restart the TDC.

#include <cstdio>
#include <cstdlib>
#include <cstring>

extern "C" {

typedef struct rp_app_params_s {
    char *name;
    float value;
    int fpga_update;
    int read_only;
    float min_val;
    float max_val;
} rp_app_params_t;

const char *rp_app_desc(void) {
    return "Pitaya TDC start/stop interval\n";
}

int rp_app_init(void) {
    fprintf(stderr, "pitaya_tdc: rp_app_init (no FPGA/server change)\n");
    return 0;
}

int rp_app_exit(void) {
    fprintf(stderr, "pitaya_tdc: rp_app_exit (leave running)\n");
    return 0;
}

int rp_set_params(rp_app_params_t *p, int len) {
    (void)p;
    (void)len;
    return 0;
}

int rp_get_params(rp_app_params_t **p) {
    if (p) {
        *p = NULL;
    }
    return 0;
}

int rp_get_signals(float ***s, int *sig_num, int *sig_len) {
    if (s) {
        *s = NULL;
    }
    if (sig_num) {
        *sig_num = 0;
    }
    if (sig_len) {
        *sig_len = 0;
    }
    return 0;
}

void UpdateSignals(void) {}
void UpdateParams(void) {}
void OnNewParams(void) {}
void OnNewSignals(void) {}
void PostUpdateSignals(void) {}

void ws_set_params_interval(int interval) { (void)interval; }
void ws_set_signals_interval(int interval) { (void)interval; }
int ws_get_params_interval(void) { return 100; }
int ws_get_signals_interval(void) { return 100; }
int ws_set_params(const char *params) {
    (void)params;
    return 0;
}
int ws_get_params(char **params) {
    if (params) {
        *params = strdup("{}");
    }
    return 0;
}
int ws_set_signals(const char *signals) {
    (void)signals;
    return 0;
}
int ws_get_signals(char **signals) {
    if (signals) {
        *signals = strdup("{}");
    }
    return 0;
}
int ws_get_bin_signals(char **signals) {
    if (signals) {
        *signals = strdup("{}");
    }
    return 0;
}
void ws_set_demo_mode(int on) { (void)on; }
int verify_app_license(void) { return 0; }

int ws_gzip(const char *in, unsigned char **data, size_t *size) {
    if (!in || !data || !size) {
        return -1;
    }
    size_t n = strlen(in) + 1;
    unsigned char *buf = (unsigned char *)malloc(n);
    if (!buf) {
        return -1;
    }
    memcpy(buf, in, n);
    *data = buf;
    *size = n;
    return 0;
}

}  // extern "C"
