#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <stdbool.h>
#include <math.h>

int main(void){

    int a, b, c;

    scanf("%d%d%d", &a, &b, &c);

    int max;

    if(a >= b && a >= c){
        max = a;
    }else if(b >= a && b >= c){
        max = b;
    }else{
        max = c;
    }

    printf("%d\n", a+b+c-max);

    return 0;
}