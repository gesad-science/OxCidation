#include <stdio.h>

int bus[24][60];

int main(void)
{
    int i, j;
    int f = 0;

    scanf("%d", &i);
    while (i-- > 0){
        int h, m;

        scanf("%d %d", &h, &m);
        bus[h][m] = 1;
    }
    scanf("%d", &i);
    while (i-- > 0){
        int h, m;

        scanf("%d %d", &h, &m);
        bus[h][m] = 1;
    }

    for (i = 0; i < 24; i++){
        for (j = 0; j < 60; j++){
            if (bus[i][j]){
                if (f){
                    printf(" %d:%02d", i, j);
                }
                else {
                    printf("%d:%02d", i, j);
                    f = 1;
                }
            }
        }
    }
    puts("");

    return 0;
}