#include <stdio.h>
#include <string.h>
 int main(void){
   int a,b,c;
   scanf("%d%d%d",&a,&b,&c);
   if(a+b+c>=22)
     printf("bust");
   else
     printf("win");
}