/*
  AOJ 2700
  Title:Airport codes
  @kankichi573
*/
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define max(x,y) (((x)>(y))?(x):(y))

int N;
const char *boin="aiueo";
char airport[100][51];
char abbrev[100][51];

int compare_str(const void *a, const void *b)
{
  return(strcmp((char *)a,(char *)b));
}

void make_abbr(char *from, char *to)
{
  char *p,*q;
  for(p=from,q=to;*p;p++)
    {
      if(p==from || strchr(boin,p[-1]))
	{
	  //printf("%c",*p);
	  *q=*p;
	  q++;
	}
    }
  q='\0';
  //printf("\n");
}

int strdiffpos(char * a,char * b)
{
  int i;
  for(i=0;i<50;i++)
    if(a[i]!=b[i])
      return(i+1);
  return(-1);
}

main()
{
  int i,ret,ret1;

  while(scanf("%d",&N)  && (N))
    {
      memset(airport,0,sizeof(airport));
      memset(abbrev ,0,sizeof(abbrev));
      for(i=0;i<N;i++)
	{
	  scanf("%s",&airport[i][0]);
	  make_abbr(&airport[i][0],&abbrev[i][0]);
	  //printf("%s\n",&abbrev[i][0]);
	}
      qsort(abbrev,N,51,compare_str);
      //for(i=0;i<N;i++)
      //	printf("%s\n",&abbrev[i][0]);
      if(N==1)
	ret=1;
      else
	ret=0;
	for(i=0;i<N-1;i++)
	  {
	    ret1=strdiffpos(&abbrev[i][0],&abbrev[i+1][0]);
	    //printf("%s %s [%d]\n",&abbrev[i][0],&abbrev[i+1][0],ret1);
	    if(ret1==-1)
	      {
		ret=-1;
		break;
	      }
	    ret=max(ret,ret1);
	  }
	printf("%d\n",ret);
    }
  return(0);
}