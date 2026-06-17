#include <float.h>
#include <limits.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

// 内部定数
#define D_CARD_MAX		100005									// 最大カード数
#define D_RATE_MAX		100000									// 最大倍数

// 内部変数
static FILE *szpFpI;											// 入力
static int si1Card[D_CARD_MAX];									// カード
static int siCCnt;												// カード数
static int siRate;												// 倍数
static int si1Single[D_RATE_MAX];								// 単体枚数
static int si1Pair[D_RATE_MAX];									// ペア枚数

// 内部変数 - テスト用
#ifdef D_TEST
	static int siRes;
	static FILE *szpFpA;
	static int siTNo;
#endif

// １行出力
int
fOutLine(
	char *pcpLine				// <I> １行
)
{
	char lc1Buf[1024];

#ifdef D_TEST
	lc1Buf[0] = '\0';
	fgets(lc1Buf, sizeof(lc1Buf), szpFpA);
	if (strcmp(lc1Buf, pcpLine)) {
		siRes = -1;
	}
#else
	printf("%s", pcpLine);
#endif

	return 0;
}

// 比較関数 - int昇順
int
fCmpFncIu(
	const void *pzpVal1			// <I> 値１
	, const void *pzpVal2		// <I> 値２
)
{
	int *lipVal1 = (int *)pzpVal1;
	int *lipVal2 = (int *)pzpVal2;

	// int昇順
	if (*lipVal1 > *lipVal2) {
		return 1;
	}
	else if (*lipVal1 < *lipVal2) {
		return -1;
	}

	return 0;
}

// 最小値 - 取得
int
fGetMin(
	int piVal1					// <I> 値１
	, int piVal2				// <I> 値２
)
{
	if (piVal1 < piVal2) {
		return piVal1;
	}
	else {
		return piVal2;
	}
}

// 実行メイン
int
fMain(
)
{
	int i;
	char lc1Buf[1024];

	// データ - 初期化
	memset(si1Single, 0, sizeof(si1Single));
	memset(si1Pair, 0, sizeof(si1Pair));

	// カード数・倍数 - 取得
	fgets(lc1Buf, sizeof(lc1Buf), szpFpI);
	sscanf(lc1Buf, "%d%d", &siCCnt, &siRate);

	// カード - 取得
	for (i = 0; i < siCCnt; i++) {
		fscanf(szpFpI, "%d", &si1Card[i]);
	}
	fgets(lc1Buf, sizeof(lc1Buf), szpFpI);

	// 枚数 - セット
	qsort(si1Card, siCCnt, sizeof(int), fCmpFncIu);
	si1Card[siCCnt] = -1;
	for (i = 0; i < siCCnt; i++) {
		if (si1Card[i] == si1Card[i + 1]) {
			si1Pair[si1Card[i] % siRate] += 2;
			i++;
		}
		else {
			si1Single[si1Card[i] % siRate]++;
		}
	}

	// 組数 - 取得 - 単体
	int liCCnt = si1Single[0] / 2;
	for (i = 1; i < siRate; i++) {
		int liNo = siRate - i;

		// 単体
		int liCnt = fGetMin(si1Single[i], si1Single[liNo]);
		liCCnt += liCnt;
		si1Single[i] -= liCnt;
		si1Single[liNo] -= liCnt;

		// ペア
		liCnt = fGetMin(si1Single[i], si1Pair[liNo]);
		liCCnt += liCnt;
		si1Single[i] -= liCnt;
		si1Pair[liNo] -= liCnt;
	}

	// 組数 - 取得 - ペア
	for (i = 0; i < siRate; i++) {
		liCCnt += si1Pair[i] / 2;
	}

	return liCCnt;
}

// １回実行
int
fOne(
)
{
	int liRet;
	char lc1Buf[1024];

	// 入力 - セット
#ifdef D_TEST
	sprintf(lc1Buf, ".\\Test\\T%d.txt", siTNo);
	szpFpI = fopen(lc1Buf, "r");
	sprintf(lc1Buf, ".\\Test\\A%d.txt", siTNo);
	szpFpA = fopen(lc1Buf, "r");
	siRes = 0;
#else
	szpFpI = stdin;
#endif

	// 実行メイン
	liRet = fMain();

	// 出力
	sprintf(lc1Buf, "%d\n", liRet);
	fOutLine(lc1Buf);

	// 残データ有無
#ifdef D_TEST
	lc1Buf[0] = '\0';
	fgets(lc1Buf, sizeof(lc1Buf), szpFpA);
	if (strcmp(lc1Buf, "")) {
		siRes = -1;
	}
#endif

	// テストファイルクローズ
#ifdef D_TEST
	fclose(szpFpI);
	fclose(szpFpA);
#endif

	// テスト結果
#ifdef D_TEST
	if (siRes == 0) {
		printf("OK %d\n", siTNo);
	}
	else {
		printf("NG %d\n", siTNo);
	}
#endif

	return 0;
}

// プログラム開始
int
main()
{

#ifdef D_TEST
	int i;
	for (i = D_TEST_SNO; i <= D_TEST_ENO; i++) {
		siTNo = i;
		fOne();
	}
#else
	fOne();
#endif

	return 0;
}

