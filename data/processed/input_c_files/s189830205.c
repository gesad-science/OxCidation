#include <stdio.h>

int main()
{
	int i, j, k, N, K;
	scanf("%d %d", &N, &K);
	if (K > (N - 1) * (N - 2) / 2) printf("-1\n");
	else {
		printf("%d\n", N * (N - 1) / 2 - K);
		for (i = 1, k = 0; i < N; i++) {
			for (j = i + 1; j <= N; j++) {
				printf("%d %d\n", i, j);
				k++;
				if (k >= N * (N - 1) / 2 - K) break;
			}
			if (j <= N) break;
		}
	}
	fflush(stdout);
	return 0;
}