#include <stdio.h>
int main(void){
  int min = 1000000010 , max = 0,dif;
  int N,Ai[100],i;
  scanf("%d",&N);

  for(i=0;i<N;i++){
    scanf("%d",&Ai[i]);
    if(Ai[i]<min){
      min = Ai[i];
    }
    if(Ai[i]>max){
      max = Ai[i];
    }
  }

  dif = max-min;

  printf("%d",dif);
     
  return 0;
}