// Lifecycle shim: nginx loads this as controllerhf.so.
// FPGA overlay is loaded by fpga.sh before rp_app_init.
// We only start/stop tdc_server.py and restore v0.94 on exit.

#include <cerrno>
#include <csignal>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

static const char *kAppDir = "/opt/redpitaya/www/apps/pitaya_tdc";
static const char *kPidFile = "/tmp/pitaya_tdc.pid";
static const char *kServerPy = "/opt/redpitaya/www/apps/pitaya_tdc/tdc_server.py";

extern "C" {

typedef struct rp_app_params_s {
    char *name;
    float value;
    int fpga_update;
    int read_only;
    float min_val;
    float max_val;
} rp_app_params_t;

static void write_pid(pid_t pid) {
    FILE *f = fopen(kPidFile, "w");
    if (!f) {
        return;
    }
    fprintf(f, "%d\n", (int)pid);
    fclose(f);
}

static pid_t read_pid(void) {
    FILE *f = fopen(kPidFile, "r");
    if (!f) {
        return -1;
    }
    int pid = -1;
    if (fscanf(f, "%d", &pid) != 1) {
        pid = -1;
    }
    fclose(f);
    return (pid_t)pid;
}

static void stop_server(void) {
    pid_t pid = read_pid();
    if (pid > 1) {
        kill(pid, SIGTERM);
        for (int i = 0; i < 20; i++) {
            if (kill(pid, 0) != 0 && errno == ESRCH) {
                break;
            }
            usleep(50000);
        }
        if (kill(pid, 0) == 0) {
            kill(pid, SIGKILL);
            usleep(50000);
        }
        waitpid(pid, NULL, WNOHANG);
    }
    unlink(kPidFile);
    /* Leftover from a crashed previous launch. */
    int wr = system("pkill -f '/opt/redpitaya/www/apps/pitaya_tdc/tdc_server.py' >/dev/null 2>&1");
    (void)wr;
}

static int start_server(void) {
    stop_server();

    pid_t pid = fork();
    if (pid < 0) {
        perror("pitaya_tdc: fork");
        return -1;
    }
    if (pid == 0) {
        if (chdir(kAppDir) != 0) {
            perror("pitaya_tdc: chdir");
            _exit(127);
        }
        setsid();
        int devnull = open("/dev/null", O_RDWR);
        if (devnull >= 0) {
            dup2(devnull, STDIN_FILENO);
            dup2(devnull, STDOUT_FILENO);
            dup2(devnull, STDERR_FILENO);
            if (devnull > 2) {
                close(devnull);
            }
        }
        execl("/usr/bin/python3", "python3", kServerPy,
              "--host", "0.0.0.0", "--port", "8080", "--udp-port", "0",
              (char *)NULL);
        execlp("python3", "python3", kServerPy,
               "--host", "0.0.0.0", "--port", "8080", "--udp-port", "0",
               (char *)NULL);
        _exit(127);
    }
    write_pid(pid);
    /* Give /dev/mem mmap a moment after the overlay load. */
    usleep(200000);
    return 0;
}

const char *rp_app_desc(void) {
    return "Pitaya TDC start/stop interval\n";
}

int rp_app_init(void) {
    fprintf(stderr, "pitaya_tdc: rp_app_init\n");
    return start_server();
}

int rp_app_exit(void) {
    fprintf(stderr, "pitaya_tdc: rp_app_exit\n");
    stop_server();
    char cmd[256];
    snprintf(cmd, sizeof(cmd), "%s/restore_fpga.sh", kAppDir);
    int rc = system(cmd);
    if (rc != 0) {
        fprintf(stderr, "pitaya_tdc: restore_fpga.sh rc=%d\n", rc);
    }
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
