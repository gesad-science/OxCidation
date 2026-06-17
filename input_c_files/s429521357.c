#include <stdio.h>

int main()
{	
	int i, N, M, A, flag[10] = {};
	scanf("%d %d", &N, &M);
	for (i = 0; i < M; i++) {
		scanf("%d", &A);
		flag[A] = 1;
	}

	int count[10] = {};
	if (flag[1] == 1) {
		if (N % 2 == 0) count[1] = N / 2;
		else if (flag[7] == 1) {
			count[1] = (N - 3) / 2;
			count[7] = 1;
		} else if (flag[5] == 1) {
			count[1] = (N - 5) / 2;
			count[5] = 1;
		} else if (flag[3] == 1) {
			count[1] = (N - 5) / 2;
			count[3] = 1;
		} else if (flag[2] == 1) {
			count[1] = (N - 5) / 2;
			count[2] = 1;
		} else {
			count[1] = (N - 7) / 2;
			count[8] = 1;
		}
	} else if (flag[7] == 1) {
		if (N % 3 == 0) count[7] = N / 3;
		else if (N % 3 == 1) {
			if (flag[4] == 1) {
				count[7] = (N - 4) / 3;
				count[4] = 1;
			} else if (flag[8] == 1) {
				count[7] = (N - 7) / 3;
				count[8] = 1;
			} else if (flag[5] == 1) {
				count[7] = (N - 10) / 3;
				count[5] = 2;
			} else if (flag[3] == 1) {
				count[7] = (N - 10) / 3;
				count[3] = 2;
			} else {
				count[7] = (N - 10) / 3;
				count[2] = 2;
			}
		} else {
			if (flag[5] == 1) {
				count[7] = (N - 5) / 3;
				count[5] = 1;
			} else if (flag[3] == 1) {
				count[7] = (N - 5) / 3;
				count[3] = 1;
			} else if (flag[2] == 1) {
				count[7] = (N - 5) / 3;
				count[2] = 1;
			} else if (flag[4] == 1) {
				count[7] = (N - 8) / 3;
				count[4] = 2;
			} else {
				count[7] = (N - 14) / 3;
				count[8] = 2;
			}
		}
	} else if (flag[4] == 1) {
		if (N % 4 == 0) count[4] = N / 4;
		else if (N % 4 == 1) {
			if (flag[5] == 1) {
				count[4] = (N - 5) / 4;
				count[5] = 1;
			} else if (flag[3] == 1) {
				count[4] = (N - 5) / 4;
				count[3] = 1;
			} else if (flag[2] == 1) {
				count[4] = (N - 5) / 4;
				count[2] = 1;
			} else if (flag[9] + flag[6] >= 1) {
				i = (flag[9] == 1)? 9: 6;
				count[4] = (N - 13) / 4;
				count[8] = 1;
				count[i] = 1;
			} else {
				count[4] = (N - 21) / 4;
				count[8] = 3;
			}
		} else if (N % 4 == 3) {
			if (N >= 11 && flag[9] == 1 && flag[5] + flag[3] + flag[2] >= 1) {
				i = (flag[5] == 1)? 5: (flag[3] == 1)? 3: 2;
				count[4] = (N - 11) / 4;
				count[i] = 1;
				count[9] = 1;
			} else if (flag[8] == 1) {
				count[4] = (N - 7) / 4;
				count[8] = 1;
			} else if (flag[6] == 1) {
				i = (flag[5] == 1)? 5: (flag[3] == 1)? 3: 2;
				count[4] = (N - 11) / 4;
				count[i] = 1;
				count[6] = 1;
			} else if (flag[5] == 1) {
				count[4] = (N - 15) / 4;
				count[5] = 3;
			} else if (flag[3] == 1) {
				count[4] = (N - 15) / 4;
				count[3] = 3;
			} else {
				count[4] = (N - 15) / 4;
				count[2] = 3;
			}
		} else if (flag[9] == 1) {
			count[4] = (N - 6) / 4;
			count[9] = 1;
		} else if (flag[6] == 1) {
			count[4] = (N - 6) / 4;
			count[6] = 1;
		} else if (flag[5] == 1) {
			count[4] = (N - 10) / 4;
			count[5] = 2;
		} else if (flag[3] == 1) {
			count[4] = (N - 10) / 4;
			count[3] = 2;
		} else if (flag[2] == 1) {
			count[4] = (N - 10) / 4;
			count[2] = 2;
		} else {
			count[4] = (N - 14) / 4;
			count[7] = 2;
		}
	} else if (flag[5] + flag[3] + flag[2] >= 1) {
		i = (flag[5] == 1)? 5: (flag[3] == 1)? 3: 2;
		if (N % 5 == 0) count[i] = N / 5;
		else if (N % 5 == 1) {
			if (flag[9] == 1) {
				count[i] = (N - 6) / 5;
				count[9] = 1;
			} else if (flag[6] = 1) {
				count[i] = (N - 6) / 5;
				count[6] = 1;
			} else {
				count[i] = (N - 21) / 5;
				count[7] = 3;
			}
		} else if (N % 5 == 2) {	
			if (N >= 12 && flag[9] == 1) {
				count[i] = (N - 12) / 5;
				count[9] = 2;
			} else if (flag[8] = 1) {
				count[i] = (N - 7) / 5;
				count[8] = 1;
			} else {
				count[i] = (N - 12) / 5;
				count[6] = 2;
			}
		} else if (N % 5 == 3) {
			if (N >= 18 && flag[9] == 1) {
				count[i] = (N - 18) / 5;
				count[9] = 3;
			} else if (flag[8] == 1 && flag[9] + flag[6] >= 1) {
				count[i] = (N - 13) / 5;
				count[8] = 1;
				if (flag[9] == 1) count[9] = 1;
				else count[6] = 1;
			} else if (flag[6] == 1) {
				count[i] = (N - 18) / 5;
				count[6] = 3;
			} else {
				count[i] = (N - 28) / 5;
				count[8] = 4;
			}
		} else {
			if (N >= 24 && flag[9] == 1) {
				count[i] = (N - 24) / 5;
				count[9] = 4;
			} else if (flag[8] == 1) {
				count[i] = (N - 14) / 5;
				count[8] = 2;
			} else {
				count[i] = (N - 24) / 5;
				count[6] = 4;
			}
		}
	} else if (flag[9] + flag[6] >= 1) {
		i = (flag[9] == 1)? 9: 6;
		count[i] = (N - N % 6 * 7) / 6;
		count[8] = N % 6;
	} else count[8] = N / 7;
	
	int j;
	for (i = 9; i >= 1; i--) {
		for (j = 0; j < count[i]; j++) printf("%d", i);
	}
	printf("\n");
	fflush(stdout);
	return 0;
}