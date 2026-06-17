#include <stdio.h>

#define N	2000
#define M	2000

int min(int a, int b) { return a < b ? a : b; }
int max(int a, int b) { return a > b ? a : b; }

int main() {
	static char cc[N][M + 1];
	static int ll[N][M], rr[N][M];
	int n, m, i, j, ans;

	scanf("%d%d", &n, &m);
	for (i = 0; i < n; i++)
		scanf("%s", cc[i]);
	for (i = 0; i < n; i++)
		for (j = 0; j < m; j++)
			cc[i][j] = cc[i][j] == '#';
	for (i = n - 1; i > 0; i--)
		for (j = m - 1; j > 0; j--)
			cc[i][j] ^= cc[i - 1][j] ^ cc[i][j - 1] ^ cc[i - 1][j - 1];
	for (i = 1; i < n; i++) {
		int k;

		k = 0;
		for (j = 1; j < m; j++)
			ll[i][j] = k = cc[i][j] == 0 ? k + 1 : 0;
		k = 0;
		for (j = m - 1; j > 0; j--)
			rr[i][j] = k = cc[i][j] == 0 ? k + 1 : 0;
	}
	ans = max(n, m);
	for (j = 1; j < m; j++) {
		int u = 0, l = m, r = m;

		for (i = 1; i < n; i++)
			if (cc[i][j] == 1)
				u = i, l = m, r = m;
			else {
				l = min(l, ll[i][j]), r = min(r, rr[i][j]);
				ans = max(ans, (i - u + 1) * (l + r));
			}
	}
	printf("%d\n", ans);
	return 0;
}
