#include <stdio.h>

int main()
{
	int K;
	scanf("%d", &K);
	
	int d, i, j, k, digit[16] = {1}, d_sum = 1;
	long long tmp = 1, pow[16];
	for (i = 1, pow[0] = 1; i < 16; i++) pow[i] = pow[i-1] * 10;
	for (k = 1, d = 0; k <= K; k++) {
		printf("%lld\n", tmp);
		
		for (i = d; digit[i] == 9; i++);
		for (tmp += pow[i], digit[i--]++, d_sum++; i >= d; tmp -= pow[i] * 9, digit[i--] = 0, d_sum -= 9);
		while (1) {
			if (digit[d] < 9) {
				if (pow[d] * d_sum >= tmp) break;
				else {
					d_sum += 9 - digit[d];
					tmp += pow[d] * (9 - digit[d]);
					digit[d++] = 9;
				}
			} else break;
		}
	}
	
	fflush(stdout);
	return 0;
}