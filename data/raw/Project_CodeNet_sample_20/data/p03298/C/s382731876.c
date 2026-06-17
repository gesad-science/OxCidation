#include <stdio.h>
#include <stdlib.h>

#define Mod 1000003

typedef struct List {
	struct List *next;
	char s[20];
	int num[2];
} list;

int hash_string(char* s)
{
	int i;
	long long x = 0;
	for (i = 0; s[i] != 0; i++) {
		x += s[i] - 'a';
		x = x << 3;
	}
	return (int)(x % Mod);
}

int lex_smaller(char* s1, char* s2)
{
	int i;
	for (i = 0; s1[i] != 0 && s2[i] != 0; i++) {
		if (s1[i] < s2[i]) return 1;
		else if (s1[i] > s2[i]) return -1;
	}
	if (s1[i] == s2[i]) return 0;
	else if (s1[i] == 0) return 1;
	else return -1;
}

int main()
{	
	int N;
	char S[40];
	scanf("%d", &N);
	scanf("%s", S);
	
	int h, i, j, k, l, bit[19];
	for (i = 1, bit[0] = 1; i <= N; i++) bit[i] = bit[i-1] << 1;
	long long ans = 0;
	char T[20] = {};
	list *hash[Mod] = {}, *p, *d = (list*)malloc(sizeof(list) * bit[N] * 2);
	for (k = 0; k < bit[N]; k++) {
		for (i = 0, j = 0, l = N - 1; i < N; i++) {
			if ((k | bit[i]) == k) T[j++] = S[i];
			else T[l--] = S[i];
		}
		T[N] = 'a' + j;
		h = hash_string(T);
		for (p = hash[h]; p != NULL; p = p->next) if (lex_smaller(p->s, T) == 0) break;
		if (p != NULL) p->num[0]++;
		else {
			for (j = 0; j <= N; j++) d[k*2].s[j] = T[j];
			d[k*2].s[N+1] = 0;
			d[k*2].num[0] = 1;
			d[k*2].num[1] = 0;
			d[k*2].next = hash[h];
			hash[h] = &(d[k*2]);
		}
		
		for (i = 0, j = 0, l = N - 1; i < N; i++) {
			if ((k | bit[i]) == k) T[j++] = S[N*2-i-1];
			else T[l--] = S[N*2-i-1];
		}
		T[N] = 'a' + j;
		h = hash_string(T);
		for (p = hash[h]; p != NULL; p = p->next) if (lex_smaller(p->s, T) == 0) break;
		if (p != NULL) p->num[1]++;
		else {
			for (j = 0; j <= N; j++) d[k*2+1].s[j] = T[j];
			d[k*2+1].s[N+1] = 0;
			d[k*2+1].num[0] = 0;
			d[k*2+1].num[1] = 1;
			d[k*2+1].next = hash[h];
			hash[h] = &(d[k*2+1]);
		}
	}
	
	for (h = 0; h < Mod; h++) {
		for (p = hash[h]; p != NULL; p = p->next) ans += (long long)(p->num[0]) * p->num[1];
	}
	printf("%lld\n", ans);
	fflush(stdout);
	return 0;
}