#include<stdio.h>
int main(){
  int a,b,i,j;
  scanf("%d%d",&a,&b);
  printf("100 100\n");
  for(i=1;i<51;i++){for(j=0;j<100;j++){a-=(i%2)*(j%2);printf("%c",((i%2)*(j%2)*(a>0))?'.':'#');}printf("\n");}
  for(i=0;i<50;i++){for(j=0;j<100;j++){b-=(i%2)*(j%2);printf("%c",((i%2)*(j%2)*(b>0))?'#':'.');}printf("\n");}
}
