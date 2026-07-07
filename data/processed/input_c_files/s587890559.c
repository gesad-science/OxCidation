#include <stdio.h>
#include <stdlib.h>

#define SIZE 320
#define NUM 320

typedef struct {
	int t, h;
	long long num;
} edge;

int main()
{
	int i, N, M, u, w, *adj[100001], deg[100001] = {}, q[100001] = {};
	long long *block[100001] = {};
	edge e[200001];
	scanf("%d %d", &N, &M);
	for (i = 0; i < N - 1; i++) {
		scanf("%d %d", &u, &w);
		e[i*2].t = u;
		e[i*2].h = w;
		e[i*2+1].t = w;
		e[i*2+1].h = u;
		e[i*2].num = -1;
		e[i*2+1].num = -1;
		deg[u]++;
		deg[w]++;
	}
	for (i = 1; i <= N; i++) {
		adj[i] = (int*)malloc(sizeof(int) * deg[i]);
		if (deg[i] > SIZE) block[i] = (long long*)malloc(sizeof(long long) * ((deg[i] + SIZE - 1) / SIZE));
	}
	for (i = 0; i < N - 1; i++) {
		u = e[i*2].t;
		w = e[i*2].h;
		adj[u][q[u]++] = i * 2;
		adj[w][q[w]++] = i * 2 + 1;
	}
	
	int par[100001] = {}, head, tail;
	long long dp[100001] = {};
	par[1] = 1;
	q[0] = 1;
	for (head = 0, tail = 1; head < tail; head++) {
		u = q[head];
		for (i = 0; i < deg[u]; i++) {
			w = e[adj[u][i]].h;
			if (par[w] == 0) {
				par[w] = u;
				q[tail++] = w;
			}
		}
	}
	for (head--; head >= 0; head--) {
		u = q[head];
		dp[u] = 1;
		for (i = 0; i < deg[u]; i++) {
			w = e[adj[u][i]].h;
			if (w == par[u]) continue;
			else {
				if (e[adj[u][i]].num == -1) e[adj[u][i]].num = dp[w];
				dp[u] = dp[u] * (e[adj[u][i]].num + 1) % M;
			}
		}
	}
	printf("%lld\n", dp[1]);
	
	int j, k;
	for (head = 0; head < tail; head++) {
		u = q[head];
		if (deg[u] > SIZE) {
			for (i = 0; i <= (deg[u] - 1) / SIZE; i++) {
				for (j = 0, block[u][i] = 1; j < SIZE && i * SIZE + j < deg[u]; j++) block[u][i] = block[u][i] * (e[adj[u][i*SIZE+j]].num + 1) % M;
			}
		}
		for (i = 0; i < deg[u]; i++) {
			if (e[adj[u][i]^1].num >= 0) continue;
			else e[adj[u][i]^1].num = 1;
			if (deg[u] > SIZE) {
				for (k = 0; k < i / SIZE; k++) e[adj[u][i]^1].num = e[adj[u][i]^1].num * block[u][k] % M;
				for (j = i / SIZE * SIZE; j < deg[u] && j < (i / SIZE + 1) * SIZE; j++) if (j != i) e[adj[u][i]^1].num = e[adj[u][i]^1].num * (e[adj[u][j]].num + 1) % M;
				for (k = i / SIZE + 1; k <= (deg[u] - 1) / SIZE; k++) e[adj[u][i]^1].num = e[adj[u][i]^1].num * block[u][k] % M;
			} else {
				for (j = 0; j < deg[u]; j++) if (j != i) e[adj[u][i]^1].num = e[adj[u][i]^1].num * (e[adj[u][j]].num + 1) % M;
			}
		}
	}
	
	long long ans;
	for (u = 2; u <= N; u++) {
		ans = 1;
		for (i = 0; i < deg[u]; i++) ans = ans * (e[adj[u][i]].num + 1) % M;
		printf("%lld\n", ans);
	}
	fflush(stdout);
	return 0;
}